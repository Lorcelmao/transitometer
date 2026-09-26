-- BR2 headway regularity and bunching, from observed passages at each stop.
-- Observed headway: gap between consecutive passages of different trips on the same route at the
-- same stop (stop ids are directional, so the stop fixes the direction). The passages are the
-- trip-stops the KPIs can use (intermediate stops, 'passed' events), plus two kinds the KPIs
-- leave out but a rider still sees, so they do not open artificial gaps:
--   scheduled    the KPI event of a scheduled trip-stop
--   ambiguous    a trip-stop passed by several vehicles; its first passage stands for the trip
--   unscheduled  a real-time trip matched to no scheduled trip (added service), on its own route
-- A vehicle never forms a headway with itself (e.g. its next trip starting to report early).
-- Passages at a trip's origin or last stop, loop stops, and stale / implausible / unconfirmed
-- events are not observed, so a real gap can appear there. The reference uses the same kind of
-- scheduled stops (intermediate, visited once); otherwise a short-turn trip ending at a stop
-- would shorten the reference there.
-- Reference: the median scheduled headway at that stop in the same hour. The hour is the service
-- hour of the observed passage. Classification of each observed headway h against reference r:
--   bunched   h <= $bunched_ratio * r
--   gap       h >= $gap_ratio * r
--   regular   |h / r - 1| <= $regular_tolerance
--   irregular otherwise

CREATE OR REPLACE TABLE scheduled_headway_ref AS
WITH intermediate AS (
    SELECT s.*
    FROM scheduled_stops s
    JOIN sched_bounds b USING (grp, service_date, trip_id)
    WHERE s.stop_sequence NOT IN (b.first_seq, b.last_seq)
    QUALIFY count(*) OVER (PARTITION BY s.grp, s.service_date, s.trip_id, s.stop_id) = 1
),
gaps AS (
    SELECT grp, service_date, route_id, stop_id,
           (sched_arrival - day_base(service_date)) // 3600 AS service_hour,
           sched_arrival - lag(sched_arrival) OVER (
               PARTITION BY grp, service_date, route_id, stop_id
               ORDER BY sched_arrival, trip_id) AS gap
    FROM intermediate
)
SELECT grp, service_date, route_id, stop_id, service_hour,
       median(gap) AS ref_headway_s, count(*) AS scheduled_gaps
FROM gaps WHERE gap > 0
GROUP BY ALL;

CREATE OR REPLACE TABLE passages AS
SELECT grp, service_date, route_id, stop_id, static_trip_id AS trip_key, trip_id, unit,
       observed_arrival,
       CASE WHEN observations > 1 THEN 'ambiguous' ELSE 'scheduled' END AS source
FROM trip_stop_events
UNION ALL
SELECT grp, service_date, rt_route_id, stop_id, 'rt:' || trip_id, trip_id, unit,
       last_prediction, 'unscheduled'
FROM (SELECT * FROM observed_events ANTI JOIN matched_trips USING (grp, trip_id, service_date))
WHERE status = 'passed' AND rt_route_id IS NOT NULL
QUALIFY row_number() OVER (
    PARTITION BY grp, service_date, trip_id, stop_id ORDER BY last_prediction, unit) = 1;

CREATE OR REPLACE TABLE headways AS
WITH ordered AS (
    SELECT grp, service_date, route_id, stop_id,
           (observed_arrival - day_base(service_date)) // 3600 AS service_hour,
           trip_key, trip_id, unit, source, observed_arrival,
           lag(trip_key) OVER w AS prev_trip_key,
           lag(unit) OVER w AS prev_unit,
           lag(source) OVER w AS prev_source,
           observed_arrival - lag(observed_arrival) OVER w AS headway_s
    FROM passages
    WINDOW w AS (PARTITION BY grp, service_date, route_id, stop_id
                 ORDER BY observed_arrival, trip_key)
)
SELECT o.* EXCLUDE (prev_unit), r.ref_headway_s,
       CASE
           WHEN o.headway_s <= $bunched_ratio * r.ref_headway_s THEN 'bunched'
           WHEN o.headway_s >= $gap_ratio * r.ref_headway_s THEN 'gap'
           WHEN abs(o.headway_s / r.ref_headway_s - 1) <= $regular_tolerance THEN 'regular'
           ELSE 'irregular'
       END AS headway_class
FROM ordered o
JOIN scheduled_headway_ref r USING (grp, service_date, route_id, stop_id, service_hour)
WHERE o.headway_s IS NOT NULL AND r.ref_headway_s > 0 AND o.unit <> o.prev_unit;

CREATE OR REPLACE TABLE headway_regularity AS
SELECT grp, service_date, route_id, service_hour, count(*) AS headways,
       round(avg((headway_class = 'regular')::INT), 4) AS regular_share,
       count(*) FILTER (WHERE headway_class = 'bunched') AS bunched,
       count(*) FILTER (WHERE headway_class = 'gap') AS gaps
FROM headways GROUP BY ALL;

CREATE OR REPLACE TABLE headway_summary AS
SELECT grp, service_date, count(*) AS headways,
       round(avg((headway_class = 'regular')::INT), 4) AS regular_share,
       round(avg((headway_class = 'bunched')::INT), 4) AS bunched_share,
       round(avg((headway_class = 'gap')::INT), 4) AS gap_share,
       round(avg((source <> 'scheduled' OR prev_source <> 'scheduled')::INT), 4)
           AS non_kpi_passage_share
FROM headways GROUP BY ALL;
