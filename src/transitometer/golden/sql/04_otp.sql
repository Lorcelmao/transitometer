-- BR1 on-time performance. An observed stop event of a schedule-matched trip is compared with
-- its scheduled arrival: delay = observed - scheduled (seconds).
-- On time: -$early_s <= delay <= $late_s (MTA band: at most 1 min early, 5 min late).
--
-- Only intermediate scheduled stops count:
--   origin    the first scheduled stop is a departure, and feeds echo its timetable time
--   terminal  the last scheduled stop: the snapshot rule measures when the trip leaves the feed,
--             not when the vehicle arrives
-- Both are reported in end_of_trip_summary as feed-quality evidence; bus terminal arrivals are
-- measured from vehicle positions instead (07_terminals.sql). Stops a scheduled trip
-- visits more than once (loops) are ambiguous and excluded.
-- One row per scheduled trip-stop (first observed passage; tie-break: unit, then real-time id).
-- A trip-stop observed by more than one reporting unit or real-time id is ambiguous: several buses
-- reporting one trip yield conflicting passages, and picking one (e.g. the first) biases delays
-- early. Ambiguous trip-stops are excluded from the KPIs and reported in ambiguous_summary (BR7).

CREATE OR REPLACE TABLE sched_bounds AS
SELECT grp, service_date, trip_id, min(stop_sequence) AS first_seq, max(stop_sequence) AS last_seq
FROM scheduled_stops GROUP BY ALL;

CREATE OR REPLACE TABLE event_candidates AS
WITH sched AS (
    SELECT *, count(*) OVER (PARTITION BY grp, service_date, trip_id, stop_id) AS visits
    FROM scheduled_stops
)
SELECT o.grp, o.service_date, o.trip_id, o.unit, m.static_trip_id, m.tier,
       s.route_id, s.direction_id, o.stop_id, s.stop_sequence, s.timepoint,
       s.sched_arrival, o.last_prediction AS observed_arrival,
       o.last_prediction - s.sched_arrival AS delay_s,
       (s.sched_arrival - day_base(o.service_date)) // 3600 AS service_hour,
       o.status,
       CASE WHEN s.stop_sequence = b.first_seq THEN 'origin'
            WHEN s.stop_sequence = b.last_seq THEN 'terminal'
            ELSE 'intermediate' END AS position
FROM observed_events o
JOIN matched_trips m USING (grp, trip_id, service_date)
JOIN sched s
  ON s.grp = o.grp AND s.service_date = o.service_date
 AND s.trip_id = m.static_trip_id AND s.stop_id = o.stop_id
JOIN sched_bounds b
  ON b.grp = s.grp AND b.service_date = s.service_date AND b.trip_id = s.trip_id
WHERE o.status IN ('passed', 'terminal') AND s.visits = 1;

-- Counted like the KPI events: one row per scheduled trip-stop, unambiguous observations only.
CREATE OR REPLACE TABLE end_of_trip_summary AS
WITH per_trip_stop AS (
    SELECT grp, service_date, position, delay_s,
           count(*) OVER (PARTITION BY grp, service_date, static_trip_id, stop_id) AS observations
    FROM event_candidates WHERE position <> 'intermediate'
)
SELECT grp, service_date, position, count(*) AS events,
       round(avg((delay_s = 0)::INT), 4) AS zero_delay_share,
       median(delay_s) AS median_delay_s
FROM per_trip_stop WHERE observations = 1
GROUP BY ALL;

-- How often the 'stale' rule fires away from the ends of a trip, where it may also drop a train
-- that was held at a station rather than a timetable echo (measured, not corrected).
CREATE OR REPLACE TABLE stale_summary AS
SELECT o.grp, o.service_date,
       CASE WHEN s.stop_sequence = b.first_seq THEN 'origin'
            WHEN s.stop_sequence = b.last_seq THEN 'terminal'
            ELSE 'intermediate' END AS position,
       count(*) AS stale_events,
       median(o.last_listed - o.last_prediction) AS median_staleness_s
FROM observed_events o
JOIN matched_trips m USING (grp, trip_id, service_date)
JOIN scheduled_stops s
  ON s.grp = o.grp AND s.service_date = o.service_date
 AND s.trip_id = m.static_trip_id AND s.stop_id = o.stop_id
JOIN sched_bounds b
  ON b.grp = s.grp AND b.service_date = s.service_date AND b.trip_id = s.trip_id
WHERE o.status = 'stale'
  -- a stop the trip visits twice cannot be placed: leave it out rather than count it per visit
  AND NOT EXISTS (SELECT 1 FROM scheduled_stops v
                  WHERE v.grp = s.grp AND v.service_date = s.service_date AND v.trip_id = s.trip_id
                    AND v.stop_id = s.stop_id AND v.stop_sequence <> s.stop_sequence)
GROUP BY ALL;

CREATE OR REPLACE TABLE trip_stop_events AS
SELECT * EXCLUDE (position),
       count(*) OVER (PARTITION BY grp, service_date, static_trip_id, stop_id) AS observations
FROM event_candidates
WHERE position = 'intermediate' AND status = 'passed'
QUALIFY row_number() OVER (
    PARTITION BY grp, service_date, static_trip_id, stop_id
    ORDER BY observed_arrival, unit, trip_id) = 1;

CREATE OR REPLACE TABLE ambiguous_summary AS
SELECT grp, service_date, count(*) AS trip_stops,
       count(*) FILTER (WHERE observations > 1) AS ambiguous_trip_stops,
       round(avg((observations > 1)::INT), 4) AS ambiguous_share
FROM trip_stop_events GROUP BY ALL;

CREATE OR REPLACE TABLE stop_events AS
SELECT * FROM trip_stop_events WHERE observations = 1;

CREATE OR REPLACE MACRO otp_class(delay) AS
    CASE WHEN delay < -$early_s THEN 'early' WHEN delay > $late_s THEN 'late' ELSE 'on_time' END;

CREATE OR REPLACE TABLE otp_summary AS
WITH scoped AS (
    SELECT grp, service_date, 'all_stops' AS scope, delay_s FROM stop_events
    UNION ALL
    SELECT grp, service_date, 'timepoints', delay_s FROM stop_events WHERE timepoint
)
SELECT grp, service_date, scope, count(*) AS events,
       round(avg((otp_class(delay_s) = 'on_time')::INT), 4) AS on_time_share,
       round(avg((otp_class(delay_s) = 'early')::INT), 4) AS early_share,
       round(avg((otp_class(delay_s) = 'late')::INT), 4) AS late_share,
       median(delay_s) AS median_delay_s
FROM scoped GROUP BY ALL;

CREATE OR REPLACE TABLE otp_route_hour AS
SELECT grp, service_date, route_id, service_hour, count(*) AS events,
       round(avg((otp_class(delay_s) = 'on_time')::INT), 4) AS on_time_share,
       round(avg((otp_class(delay_s) = 'late')::INT), 4) AS late_share,
       median(delay_s) AS median_delay_s
FROM stop_events GROUP BY ALL;

-- Guard for service-day assignment: a KPI event more than 6 h off its timetable almost always
-- means a trip was matched to the wrong service day (expected ~0).
CREATE OR REPLACE TABLE delay_sanity_summary AS
SELECT grp, service_date, count(*) AS events,
       count(*) FILTER (WHERE abs(delay_s) > 6 * 3600) AS events_over_6h
FROM stop_events GROUP BY ALL;
