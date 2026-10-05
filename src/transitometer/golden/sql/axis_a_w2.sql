-- Axis A W2: the BR2 headway rule of 05_headways.sql, computed from axis_a_passages only.
-- Per (grp, service_date, route, stop), passages in (observed_arrival, trip_key) order; each one
-- forms a headway with the one before it. The chain runs through every passage, including those
-- whose headway is then dropped (no reference, or the same vehicle twice). Its result must equal
-- the golden `headways` table, which proves the passage export complete.

CREATE OR REPLACE TABLE axis_a_w2 AS
WITH ordered AS (
    SELECT grp, service_date, route_id, stop_id, service_hour,
           trip_key, trip_id, unit, source, observed_arrival, ref_headway_s,
           lag(trip_key) OVER w AS prev_trip_key,
           lag(unit) OVER w AS prev_unit,
           lag(source) OVER w AS prev_source,
           observed_arrival - lag(observed_arrival) OVER w AS headway_s
    FROM axis_a_passages
    WINDOW w AS (PARTITION BY grp, service_date, route_id, stop_id
                 ORDER BY observed_arrival, trip_key)
)
SELECT grp, service_date, route_id, stop_id, service_hour, trip_key, trip_id, unit, source,
       observed_arrival, prev_trip_key, prev_source, headway_s, ref_headway_s,
       CASE
           WHEN headway_s <= $bunched_ratio * ref_headway_s THEN 'bunched'
           WHEN headway_s >= $gap_ratio * ref_headway_s THEN 'gap'
           WHEN abs(headway_s / ref_headway_s - 1) <= $regular_tolerance THEN 'regular'
           ELSE 'irregular'
       END AS headway_class
FROM ordered
WHERE headway_s IS NOT NULL AND ref_headway_s > 0 AND unit <> prev_unit;
