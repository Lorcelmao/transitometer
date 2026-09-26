-- BR3 missing trips: promised (scheduled) vs delivered (observed) service.
-- Each scheduled trip active on a service day, on a route the real-time feed carries that day,
-- gets exactly one delivery class, checked in this order:
--   delivered  reported, and at least $partial_share of its intermediate stops observed passed
--              (a trip without intermediate stops only needs to be reported)
--   unknown    not delivered, and the feed cannot tell: the scheduled span falls outside the
--              snapshots read, or overlaps a gap of more than $outage_gap_s s between snapshots
--   missing    never reported under any trip-matching tier
--   not_run    reported, but never observed moving: no intermediate stop passed and no measured
--              arrival at the last stop (announced service that did not run, e.g. cancelled or
--              reassigned to another trip id)
--   partial    observed running, but fewer intermediate stops passed than required
-- Not delivered = missing + not_run; keeping them apart shows how much the feed announces
-- without running it (feed quality, BR7).
-- Subway caveat: about 11 % of subway real-time trips match no scheduled trip, so part of the
-- subway 'missing' count is service that ran under an id the matching could not resolve.

CREATE OR REPLACE TABLE feed_snapshots AS
SELECT DISTINCT 'bus' AS grp, feed_timestamp::BIGINT AS ts FROM read_parquet($bus_tu)
UNION
SELECT DISTINCT 'subway', feed_timestamp::BIGINT FROM read_parquet($subway_tu);

CREATE OR REPLACE TABLE feed_outages AS
SELECT grp, prev_ts AS gap_start, ts AS gap_end
FROM (SELECT grp, ts, lag(ts) OVER (PARTITION BY grp ORDER BY ts) AS prev_ts FROM feed_snapshots)
WHERE ts - prev_ts > $outage_gap_s;

CREATE OR REPLACE TABLE feed_coverage AS
SELECT grp, min(ts) AS first_snapshot, max(ts) AS last_snapshot FROM feed_snapshots GROUP BY ALL;

CREATE OR REPLACE TABLE trip_delivery AS
WITH spans AS (
    SELECT s.grp, s.service_date, s.trip_id, any_value(s.route_id) AS route_id,
           any_value(s.direction_id) AS direction_id,
           min(s.sched_arrival) AS sched_start, max(s.sched_arrival) AS sched_end,
           count(DISTINCT s.stop_id) FILTER (
               WHERE s.stop_sequence NOT IN (b.first_seq, b.last_seq)) AS intermediate_stops
    FROM scheduled_stops s
    JOIN sched_bounds b USING (grp, service_date, trip_id)
    GROUP BY ALL
),
feed_routes AS (
    SELECT DISTINCT a.grp, a.service_date, a.route_id
    FROM matched_trips m
    JOIN active_trips a
      ON a.grp = m.grp AND a.service_date = m.service_date AND a.trip_id = m.static_trip_id
),
reported AS (
    SELECT DISTINCT grp, service_date, static_trip_id AS trip_id FROM matched_trips
),
passed AS (
    SELECT grp, service_date, static_trip_id AS trip_id, count(DISTINCT stop_id) AS passed_stops
    FROM trip_stop_events GROUP BY ALL
),
arrived AS (
    SELECT DISTINCT grp, service_date, static_trip_id AS trip_id FROM terminal_candidates
),
flagged AS (
    SELECT s.*, (r.trip_id IS NOT NULL) AS reported, coalesce(p.passed_stops, 0) AS passed_stops,
           (a.trip_id IS NOT NULL) AS arrived,
           s.sched_start < c.first_snapshot OR s.sched_end > c.last_snapshot
           OR EXISTS (SELECT 1 FROM feed_outages o
                      WHERE o.grp = s.grp AND o.gap_start < s.sched_end
                        AND o.gap_end > s.sched_start) AS unobservable
    FROM spans s
    JOIN feed_routes USING (grp, service_date, route_id)
    JOIN feed_coverage c USING (grp)
    LEFT JOIN reported r USING (grp, service_date, trip_id)
    LEFT JOIN passed p USING (grp, service_date, trip_id)
    LEFT JOIN arrived a USING (grp, service_date, trip_id)
)
SELECT grp, service_date, trip_id, route_id, direction_id, sched_start, sched_end,
       (sched_start - day_base(service_date)) // 3600 AS service_hour,
       intermediate_stops, passed_stops, reported, arrived,
       CASE
           WHEN reported AND passed_stops >= $partial_share * intermediate_stops THEN 'delivered'
           WHEN unobservable THEN 'unknown'
           WHEN NOT reported THEN 'missing'
           WHEN passed_stops = 0 AND NOT arrived THEN 'not_run'
           ELSE 'partial'
       END AS delivery
FROM flagged;

CREATE OR REPLACE TABLE missing_trip_summary AS
SELECT grp, service_date, count(*) AS scheduled,
       count(*) FILTER (WHERE delivery = 'delivered') AS delivered,
       count(*) FILTER (WHERE delivery = 'partial') AS partial,
       count(*) FILTER (WHERE delivery = 'missing') AS missing,
       count(*) FILTER (WHERE delivery = 'not_run') AS not_run,
       count(*) FILTER (WHERE delivery = 'unknown') AS unknown,
       round(count(*) FILTER (WHERE delivery = 'missing')
             / nullif(count(*) FILTER (WHERE delivery <> 'unknown'), 0), 4) AS missing_share,
       round(count(*) FILTER (WHERE delivery IN ('missing', 'not_run'))
             / nullif(count(*) FILTER (WHERE delivery <> 'unknown'), 0), 4) AS not_delivered_share
FROM trip_delivery GROUP BY ALL;

CREATE OR REPLACE TABLE missing_by_route AS
SELECT grp, service_date, route_id, count(*) AS scheduled,
       count(*) FILTER (WHERE delivery = 'delivered') AS delivered,
       count(*) FILTER (WHERE delivery = 'partial') AS partial,
       count(*) FILTER (WHERE delivery = 'missing') AS missing,
       count(*) FILTER (WHERE delivery = 'not_run') AS not_run,
       count(*) FILTER (WHERE delivery = 'unknown') AS unknown,
       round(count(*) FILTER (WHERE delivery = 'missing')
             / nullif(count(*) FILTER (WHERE delivery <> 'unknown'), 0), 4) AS missing_share,
       round(count(*) FILTER (WHERE delivery IN ('missing', 'not_run'))
             / nullif(count(*) FILTER (WHERE delivery <> 'unknown'), 0), 4) AS not_delivered_share
FROM trip_delivery GROUP BY ALL;
