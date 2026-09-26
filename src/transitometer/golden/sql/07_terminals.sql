-- Bus arrivals at the last scheduled stop, measured from vehicle positions.
-- Trip updates cannot place this arrival: the stop only leaves the update list when the trip
-- leaves the feed (see 04_otp.sql). A vehicle position is a GPS fix, so the arrival is the first
-- fix of the vehicle, still reporting this trip, within $terminal_radius_m metres of the last stop.
-- Only fixes at or after the vehicle's last passed stop on the trip count, so a loop route whose
-- last stop lies next to its first is not "arrived" when it departs.
-- Like the other KPI events: one row per scheduled trip-stop; several vehicles = ambiguous.
-- Reported as a separate 'terminals' scope; subway has no vehicle positions in this feed.

-- One coordinate pair per stop id, taken from a single row when schedule versions disagree.
CREATE OR REPLACE TABLE bus_stop_geo AS
SELECT stop_id, pos.lat AS lat, pos.lon AS lon
FROM (SELECT CAST(stop_id AS VARCHAR) AS stop_id,
             min({'lat': CAST(stop_lat AS DOUBLE), 'lon': CAST(stop_lon AS DOUBLE)}) AS pos
      FROM read_parquet($bus_stops, union_by_name = true)
      WHERE stop_lat IS NOT NULL AND stop_lon IS NOT NULL
      GROUP BY ALL);

CREATE OR REPLACE TABLE terminal_targets AS
SELECT m.grp, m.service_date, m.trip_id, m.static_trip_id, s.route_id, s.stop_id, s.sched_arrival,
       g.lat, g.lon
FROM matched_trips m
JOIN sched_bounds b
  ON b.grp = m.grp AND b.service_date = m.service_date AND b.trip_id = m.static_trip_id
JOIN scheduled_stops s
  ON s.grp = b.grp AND s.service_date = b.service_date AND s.trip_id = b.trip_id
 AND s.stop_sequence = b.last_seq
JOIN bus_stop_geo g ON g.stop_id = s.stop_id
WHERE m.grp = 'bus';

CREATE OR REPLACE TABLE terminal_candidates AS
WITH last_pass AS (
    SELECT trip_id, service_date, unit, max(last_prediction) AS last_passed
    FROM observed_events WHERE grp = 'bus' AND status = 'passed'
    GROUP BY ALL
),
fixes AS (
    SELECT trip_id, start_date AS service_date, vehicle_id AS unit,
           coalesce(timestamp, feed_timestamp)::BIGINT AS ts,
           CAST(latitude AS DOUBLE) AS lat, CAST(longitude AS DOUBLE) AS lon
    FROM read_parquet($bus_vp)
    WHERE trip_id IS NOT NULL AND vehicle_id IS NOT NULL AND vehicle_id <> ''
      AND latitude IS NOT NULL AND longitude IS NOT NULL
      AND start_date IN (SELECT service_date FROM service_days)
)
SELECT t.grp, t.service_date, t.trip_id, t.static_trip_id, t.route_id, t.stop_id,
       t.sched_arrival, f.unit, min(f.ts) AS observed_arrival
FROM terminal_targets t
JOIN fixes f ON f.trip_id = t.trip_id AND f.service_date = t.service_date
JOIN last_pass p ON p.trip_id = f.trip_id AND p.service_date = f.service_date AND p.unit = f.unit
-- Equirectangular distance: exact enough within a city at this radius.
WHERE f.ts >= p.last_passed
  AND pow((f.lat - t.lat) * 111320, 2)
      + pow((f.lon - t.lon) * 111320 * cos(radians(t.lat)), 2) <= pow($terminal_radius_m, 2)
GROUP BY ALL;

CREATE OR REPLACE TABLE terminal_events AS
SELECT grp, service_date, static_trip_id, trip_id, unit, route_id, stop_id, sched_arrival,
       observed_arrival, observed_arrival - sched_arrival AS delay_s,
       (sched_arrival - day_base(service_date)) // 3600 AS service_hour,
       count(*) OVER (PARTITION BY grp, service_date, static_trip_id) AS observations
FROM terminal_candidates
QUALIFY row_number() OVER (
    PARTITION BY grp, service_date, static_trip_id
    ORDER BY observed_arrival, unit, trip_id) = 1;

CREATE OR REPLACE TABLE terminal_summary AS
SELECT t.grp, t.service_date, count(*) AS matched_trips,
       count(e.static_trip_id) FILTER (WHERE e.observations = 1) AS measured,
       count(e.static_trip_id) FILTER (WHERE e.observations > 1) AS ambiguous,
       round(count(e.static_trip_id) FILTER (WHERE e.observations = 1) / count(*), 4)
           AS measured_share,
       median(e.delay_s) FILTER (WHERE e.observations = 1) AS median_delay_s
FROM (SELECT DISTINCT grp, service_date, static_trip_id FROM terminal_targets) t
LEFT JOIN terminal_events e USING (grp, service_date, static_trip_id)
GROUP BY ALL;

INSERT INTO otp_summary
SELECT grp, service_date, 'terminals' AS scope, count(*) AS events,
       round(avg((otp_class(delay_s) = 'on_time')::INT), 4) AS on_time_share,
       round(avg((otp_class(delay_s) = 'early')::INT), 4) AS early_share,
       round(avg((otp_class(delay_s) = 'late')::INT), 4) AS late_share,
       median(delay_s) AS median_delay_s
FROM terminal_events WHERE observations = 1
GROUP BY ALL;
