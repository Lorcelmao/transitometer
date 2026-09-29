-- BR7 feed data-quality monitor: per feed and day, a set of metrics, each checked against a
-- declared threshold (feed_quality_thresholds, lower is better for all). The conformance score is
-- the share of applicable checks that pass (0-100); the metric values are exported beside it.
-- Every feed gets every applicable check on every service day: a feed with no data fails them
-- all (value NULL) instead of disappearing from the scores.
-- Snapshot and record metrics use the local calendar day of the snapshot; trip and event
-- metrics use the service day (the same labels for the golden window).
--   max_gap_s              longest gap between the header timestamps of consecutive snapshots
--   missed_poll_share      gaps between the archive fetch times of consecutive snapshots longer
--                          than 1.5 x the feed's median fetch interval: a poll that returned no
--                          new snapshot. Measured on fetch times, the archive's own regular
--                          clock; header timestamps drift with the feed's publication lag (a
--                          30 s poll plus lag differences gives header gaps up to ~66 s with no
--                          loss). An earlier header-based definition was revised after seeing the
--                          development day, where it flagged that jitter.
--   header_lag_p99_s       archive fetch time - feed header timestamp, 99th percentile
--   unknown_stop_share     listed stops (trip, vehicle, stop per service day; see stop_last)
--                          whose stop_id is not in the timetable's stops
--   unknown_trip_share     real-time trips matched to no scheduled trip ('unscheduled')
--   stuck_share            stop events whose prediction stayed listed long after it passed
--                          ('stale': more than $max_stale_s s in the past)
--   not_run_share          scheduled trips announced in the feed but never seen moving (BR3)
--   ambiguous_share        KPI trip-stops reported by more than one vehicle or real-time id
--   fix_age_p99_s          feed header timestamp - vehicle fix timestamp, 99th percentile
--   stale_fix_share        vehicle fixes older than 120 s when published
--   jump_share             consecutive fixes of a vehicle more than 200 m apart at an implied
--                          speed above 30 m/s (108 km/h): a GPS jump, listed in position_jumps
--   out_of_bbox_share      fixes outside the NYC service area (lat 40.4-41.0, lon -74.3 to -73.6)

CREATE OR REPLACE TABLE feed_quality_thresholds AS
SELECT metric, CAST(threshold AS DOUBLE) AS threshold FROM (VALUES
    ('max_gap_s', 120.0), ('missed_poll_share', 0.01), ('header_lag_p99_s', 60.0),
    ('unknown_stop_share', 0.01), ('unknown_trip_share', 0.05), ('stuck_share', 0.02),
    ('not_run_share', 0.02), ('ambiguous_share', 0.02), ('fix_age_p99_s', 60.0),
    ('stale_fix_share', 0.01), ('jump_share', 0.001), ('out_of_bbox_share', 0.001)
) AS t(metric, threshold);

CREATE OR REPLACE MACRO local_day(ts) AS
    strftime(timezone('$timezone', to_timestamp(ts)), '%Y%m%d');

CREATE OR REPLACE TABLE known_stops AS
SELECT DISTINCT 'bus' AS grp, CAST(stop_id AS VARCHAR) AS stop_id
FROM read_parquet($bus_stops, union_by_name = true)
UNION
SELECT DISTINCT 'subway', CAST(stop_id AS VARCHAR)
FROM read_parquet($subway_stops, union_by_name = true);

-- One row per snapshot: archive fetch time and header lag. Reads only the two header columns.
CREATE OR REPLACE TABLE feed_snapshot_stats AS
WITH snapshots AS (
    SELECT 'bus_tu' AS feed, feed_timestamp, max(fetch_timestamp) AS fetch_timestamp
    FROM read_parquet($bus_tu) GROUP BY feed_timestamp
    UNION ALL
    SELECT 'subway_tu', feed_timestamp, max(fetch_timestamp)
    FROM read_parquet($subway_tu) GROUP BY feed_timestamp
    UNION ALL
    SELECT 'bus_vp', feed_timestamp, max(fetch_timestamp)
    FROM read_parquet($bus_vp) GROUP BY feed_timestamp
)
SELECT feed, feed_timestamp::BIGINT AS ts, epoch(fetch_timestamp) AS fetched,
       epoch(fetch_timestamp) - feed_timestamp::BIGINT AS header_lag_s
FROM snapshots;

CREATE OR REPLACE TABLE fixes AS
SELECT DISTINCT vehicle_id, feed_timestamp::BIGINT AS feed_ts, timestamp::BIGINT AS ts,
       CAST(latitude AS DOUBLE) AS lat, CAST(longitude AS DOUBLE) AS lon
FROM read_parquet($bus_vp)
WHERE vehicle_id IS NOT NULL AND vehicle_id <> '' AND timestamp IS NOT NULL
  AND latitude IS NOT NULL AND longitude IS NOT NULL;

-- Steps between consecutive fixes of a vehicle; a fix republished in several snapshots counts
-- once, with the position and day of its first publication (one row: no mixed coordinates).
CREATE OR REPLACE TABLE fix_steps AS
WITH f AS (
    SELECT vehicle_id, ts, first.feed_ts AS feed_ts, first.lat AS lat, first.lon AS lon
    FROM (SELECT vehicle_id, ts, min({'feed_ts': feed_ts, 'lat': lat, 'lon': lon}) AS first
          FROM fixes GROUP BY ALL)
),
steps AS (
    SELECT vehicle_id, ts, feed_ts, lat, lon,
           lag(ts) OVER w AS prev_ts, lag(lat) OVER w AS prev_lat, lag(lon) OVER w AS prev_lon
    FROM f WINDOW w AS (PARTITION BY vehicle_id ORDER BY ts)
),
measured AS (
    SELECT *, sqrt(pow((lat - prev_lat) * 111320, 2)
                   + pow((lon - prev_lon) * 111320 * cos(radians(lat)), 2)) AS distance_m
    FROM steps WHERE prev_ts IS NOT NULL AND ts > prev_ts
)
SELECT local_day(feed_ts) AS day, vehicle_id, prev_ts, ts, distance_m,
       distance_m > 200 AND distance_m / (ts - prev_ts) > 30 AS jump
FROM measured;

-- The golden days only: the archive partitions read also cover parts of the neighbouring days.
CREATE OR REPLACE TABLE position_jumps AS
SELECT day, vehicle_id, prev_ts, ts, round(distance_m) AS distance_m,
       round(distance_m / (ts - prev_ts), 1) AS speed_mps
FROM fix_steps WHERE jump AND day IN (SELECT service_date FROM service_days);

CREATE OR REPLACE TABLE feed_quality_metrics AS
WITH snaps AS (
    SELECT *, ts - lag(ts) OVER (PARTITION BY feed ORDER BY ts) AS gap_s,
           fetched - lag(fetched) OVER (PARTITION BY feed ORDER BY fetched, ts) AS fetch_gap_s
    FROM feed_snapshot_stats
),
poll AS (SELECT feed, median(fetch_gap_s) AS median_fetch_gap_s FROM snaps GROUP BY ALL),
snap_day AS (
    SELECT s.feed, local_day(s.ts) AS day,
           max(s.gap_s)::DOUBLE AS max_gap_s,
           count(*) FILTER (WHERE s.fetch_gap_s > 1.5 * p.median_fetch_gap_s)
               / count(s.fetch_gap_s) AS missed_poll_share,
           quantile_cont(s.header_lag_s, 0.99) AS header_lag_p99_s
    FROM snaps s JOIN poll p USING (feed)
    GROUP BY ALL
),
fix_day AS (
    SELECT 'bus_vp' AS feed, local_day(feed_ts) AS day,
           quantile_cont(feed_ts - ts, 0.99) AS fix_age_p99_s,
           avg((feed_ts - ts > 120)::INT) AS stale_fix_share,
           avg((lat NOT BETWEEN 40.4 AND 41.0 OR lon NOT BETWEEN -74.3 AND -73.6)::INT)
               AS out_of_bbox_share
    FROM fixes GROUP BY ALL
),
jump_day AS (
    SELECT 'bus_vp' AS feed, day, avg(jump::INT) AS jump_share FROM fix_steps GROUP BY ALL
),
stop_day AS (
    SELECT l.grp || '_tu' AS feed, l.service_date AS day,
           avg((k.stop_id IS NULL)::INT) AS unknown_stop_share
    FROM stop_last l
    LEFT JOIN known_stops k ON k.grp = l.grp AND k.stop_id = l.stop_id
    GROUP BY ALL
),
trip_day AS (
    SELECT grp || '_tu' AS feed, service_date AS day,
           coalesce(sum(rt_trips) FILTER (WHERE tier = 'unscheduled'), 0) / sum(rt_trips)
               AS unknown_trip_share
    FROM trip_match_summary GROUP BY ALL
),
event_day AS (
    SELECT grp || '_tu' AS feed, service_date AS day,
           coalesce(sum(events) FILTER (WHERE status = 'stale'), 0) / sum(events) AS stuck_share
    FROM event_status_summary GROUP BY ALL
),
delivery_day AS (
    SELECT grp || '_tu' AS feed, service_date AS day,
           not_run / nullif(scheduled - unknown, 0) AS not_run_share
    FROM missing_trip_summary
),
ambiguous_day AS (
    SELECT grp || '_tu' AS feed, service_date AS day, ambiguous_trip_stops / trip_stops
        AS ambiguous_share
    FROM ambiguous_summary
),
long AS (
    UNPIVOT (SELECT * FROM snap_day) ON max_gap_s, missed_poll_share, header_lag_p99_s
        INTO NAME metric VALUE value
    UNION ALL UNPIVOT stop_day ON unknown_stop_share INTO NAME metric VALUE value
    UNION ALL
    UNPIVOT fix_day ON fix_age_p99_s, stale_fix_share, out_of_bbox_share
        INTO NAME metric VALUE value
    UNION ALL UNPIVOT jump_day ON jump_share INTO NAME metric VALUE value
    UNION ALL UNPIVOT trip_day ON unknown_trip_share INTO NAME metric VALUE value
    UNION ALL UNPIVOT event_day ON stuck_share INTO NAME metric VALUE value
    UNION ALL UNPIVOT delivery_day ON not_run_share INTO NAME metric VALUE value
    UNION ALL UNPIVOT ambiguous_day ON ambiguous_share INTO NAME metric VALUE value
)
, checks AS (
    SELECT feed, metric
    FROM (VALUES ('bus_tu'), ('subway_tu'), ('bus_vp')) f(feed)
    CROSS JOIN (SELECT metric FROM feed_quality_thresholds) m
    WHERE metric IN ('max_gap_s', 'missed_poll_share', 'header_lag_p99_s')
       OR (feed LIKE '%_tu' AND metric IN ('unknown_stop_share', 'unknown_trip_share',
                                           'stuck_share', 'not_run_share', 'ambiguous_share'))
       OR (feed = 'bus_vp' AND metric IN ('fix_age_p99_s', 'stale_fix_share', 'jump_share',
                                          'out_of_bbox_share'))
)
SELECT c.feed, d.service_date AS day, c.metric, round(l.value, 6) AS value, t.threshold,
       coalesce(round(l.value, 6) <= t.threshold, false) AS passed
FROM checks c
CROSS JOIN service_days d
JOIN feed_quality_thresholds t USING (metric)
LEFT JOIN long l ON l.feed = c.feed AND l.metric = c.metric AND l.day = d.service_date;

CREATE OR REPLACE TABLE feed_quality_score AS
SELECT feed, day, count(*) AS checks, count(*) FILTER (WHERE passed) AS passed,
       round(100 * count(*) FILTER (WHERE passed) / count(*), 1) AS score,
       string_agg(metric, ', ' ORDER BY metric) FILTER (WHERE NOT passed) AS failed_checks
FROM feed_quality_metrics GROUP BY ALL;
