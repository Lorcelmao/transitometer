-- BR2 headway regularity and bunching, from observed arrivals at each stop.
-- Observed headway: gap between consecutive observed arrivals of different trips on the same
-- route, direction and stop. Reference: the median scheduled headway at that stop in the same
-- service hour. Classification of each observed headway h against reference r:
--   bunched   h <= $bunched_ratio * r
--   gap       h >= $gap_ratio * r
--   regular   |h / r - 1| <= $regular_tolerance
--   irregular otherwise

CREATE OR REPLACE TABLE scheduled_headway_ref AS
WITH gaps AS (
    SELECT grp, service_date, route_id, direction_id, stop_id,
           (sched_arrival - day_base(service_date)) // 3600 AS service_hour,
           sched_arrival - lag(sched_arrival) OVER (
               PARTITION BY grp, service_date, route_id, direction_id, stop_id
               ORDER BY sched_arrival, trip_id) AS gap
    FROM scheduled_stops
)
SELECT grp, service_date, route_id, direction_id, stop_id, service_hour,
       median(gap) AS ref_headway_s, count(*) AS scheduled_gaps
FROM gaps WHERE gap > 0
GROUP BY ALL;

CREATE OR REPLACE TABLE headways AS
WITH ordered AS (
    SELECT grp, service_date, route_id, direction_id, stop_id, service_hour, trip_id,
           static_trip_id, observed_arrival,
           lag(static_trip_id) OVER w AS prev_static_trip_id,
           observed_arrival - lag(observed_arrival) OVER w AS headway_s
    FROM stop_events
    WINDOW w AS (PARTITION BY grp, service_date, route_id, direction_id, stop_id
                 ORDER BY observed_arrival, static_trip_id)
)
SELECT o.*, r.ref_headway_s,
       CASE
           WHEN o.headway_s <= $bunched_ratio * r.ref_headway_s THEN 'bunched'
           WHEN o.headway_s >= $gap_ratio * r.ref_headway_s THEN 'gap'
           WHEN abs(o.headway_s / r.ref_headway_s - 1) <= $regular_tolerance THEN 'regular'
           ELSE 'irregular'
       END AS headway_class
FROM ordered o
JOIN scheduled_headway_ref r USING (grp, service_date, route_id, direction_id, stop_id, service_hour)
WHERE o.headway_s IS NOT NULL AND r.ref_headway_s > 0;

CREATE OR REPLACE TABLE headway_regularity AS
SELECT grp, service_date, route_id, direction_id, service_hour, count(*) AS headways,
       round(avg((headway_class = 'regular')::INT), 4) AS regular_share,
       count(*) FILTER (WHERE headway_class = 'bunched') AS bunched,
       count(*) FILTER (WHERE headway_class = 'gap') AS gaps
FROM headways GROUP BY ALL;

CREATE OR REPLACE TABLE headway_summary AS
SELECT grp, service_date, count(*) AS headways,
       round(avg((headway_class = 'regular')::INT), 4) AS regular_share,
       round(avg((headway_class = 'bunched')::INT), 4) AS bunched_share,
       round(avg((headway_class = 'gap')::INT), 4) AS gap_share
FROM headways GROUP BY ALL;
