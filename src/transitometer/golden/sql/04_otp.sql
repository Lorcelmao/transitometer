-- BR1 on-time performance. An observed stop event of a schedule-matched trip is compared with
-- its scheduled arrival: delay = observed - scheduled (seconds).
-- On time: -$early_s <= delay <= $late_s (MTA band: at most 1 min early, 5 min late).
--
-- Only intermediate scheduled stops count:
--   origin    the first scheduled stop is a departure, and feeds echo its timetable time
--   terminal  the last scheduled stop: the snapshot rule measures when the trip leaves the feed,
--             not when the vehicle arrives (to be measured from vehicle positions later)
-- Both are reported in end_of_trip_summary as feed-quality evidence. Stops a scheduled trip
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

CREATE OR REPLACE TABLE end_of_trip_summary AS
SELECT grp, service_date, position, count(*) AS events,
       round(avg((delay_s = 0)::INT), 4) AS zero_delay_share,
       median(delay_s) AS median_delay_s
FROM event_candidates WHERE position <> 'intermediate'
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
