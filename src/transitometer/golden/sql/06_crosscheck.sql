-- Cross-check of bus stop events from vehicle positions (a different message type and rule).
-- A vehicle position carries the NEXT stop. When the next stop changes from A to B between two
-- consecutive positions of the same vehicle on the same trip at t_before and t_after, the
-- vehicle passed A in that interval. The trip-update event for A agrees if its observed arrival
-- falls within [t_before - $crosscheck_slack_s, t_after + $crosscheck_slack_s].
-- Both feeds come from the same AVL system: this independently checks the INFERENCE rule, not
-- the underlying sensor.

CREATE OR REPLACE TABLE vp_passages AS
WITH vp AS (
    SELECT DISTINCT trip_id, start_date AS service_date, vehicle_id, stop_id,
           coalesce(timestamp, feed_timestamp)::BIGINT AS ts, feed_timestamp::BIGINT AS feed_ts
    FROM read_parquet($bus_vp)
    WHERE trip_id IS NOT NULL AND trip_id <> '' AND stop_id IS NOT NULL
      AND vehicle_id IS NOT NULL AND vehicle_id <> ''
      AND start_date IN (SELECT service_date FROM service_days)
),
seq AS (
    SELECT *, lag(stop_id) OVER w AS prev_stop, lag(ts) OVER w AS prev_ts
    -- A vehicle timestamp can repeat across snapshots with a changed next stop; the snapshot
    -- time orders those, so passages are never recorded backwards.
    FROM vp WINDOW w AS (PARTITION BY trip_id, service_date, vehicle_id
                         ORDER BY ts, feed_ts, stop_id)
)
SELECT trip_id, service_date, vehicle_id, prev_stop AS passed_stop, prev_ts AS t_before,
       ts AS t_after
FROM seq
WHERE prev_stop IS NOT NULL AND prev_stop <> stop_id;

-- One row per stop event: a stop can yield several passages when the reported next stop flips
-- back and forth, so an event agrees if ANY of its passage windows contains the observed time.
CREATE OR REPLACE TABLE crosscheck AS
SELECT e.service_date, e.trip_id, e.stop_id, e.observed_arrival,
       count(*) AS passages,
       bool_or(e.observed_arrival BETWEEN p.t_before - $crosscheck_slack_s
                                      AND p.t_after + $crosscheck_slack_s) AS agrees,
       min(abs(e.observed_arrival - p.t_after)) AS nearest_offset_s
FROM stop_events e
JOIN vp_passages p
  ON p.trip_id = e.trip_id AND p.service_date = e.service_date AND p.vehicle_id = e.unit
 AND p.passed_stop = e.stop_id
WHERE e.grp = 'bus'
GROUP BY ALL;

CREATE OR REPLACE TABLE crosscheck_summary AS
SELECT service_date, count(*) AS compared, round(avg(agrees::INT), 4) AS agreement_share,
       round(avg((passages > 1)::INT), 4) AS multi_passage_share,
       median(nearest_offset_s) AS median_abs_offset_s
FROM crosscheck GROUP BY ALL;
