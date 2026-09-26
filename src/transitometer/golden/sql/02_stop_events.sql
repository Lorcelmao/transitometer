-- Observed stop events inferred from repeated trip-update snapshots.
--
-- Rule: a trip update lists the stops a vehicle has not yet served. When a stop disappears from
-- the list while the trip is still being reported, the vehicle has served it; the arrival time
-- predicted in the LAST snapshot that still listed the stop is the observed arrival.
--
-- status:
--   passed          stop dropped out while the trip was still reported afterwards
--   terminal        trip's final stop: it is the only stop in the trip's last snapshot and its
--                   predicted arrival is no later than that snapshot + $terminal_grace_s
--   unconfirmed     trip vanished while this stop was still pending (feed gap or cancellation)
--   implausible     stop dropped out but its last prediction lay more than $max_lead_s seconds
--                   after the last time it was listed (skipped stop, reroute, or re-prediction)
--   stale           the last prediction was already more than $max_stale_s seconds in the past
--                   when the stop was last listed: the feed was echoing a fixed (often scheduled)
--                   time rather than tracking the vehicle, typically at origin terminals
-- Only 'passed' events of intermediate scheduled stops feed the KPIs (see 04_otp.sql).
--
-- Inference runs per reporting unit: the vehicle_id when the feed carries one (MTA Bus: always),
-- else the trip itself. Two vehicles can report the same bus trip, and merging them would mix
-- their predictions. NYCT subway sends no vehicle_id and its entity_id is only the entity's
-- position within each snapshot ('000001', ...), so it carries no identity; the rare subway
-- snapshot with two entities for one trip stays merged and is resolved by the arg_max order.
-- Every aggregate has a total order, so results are deterministic regardless of thread scheduling.

CREATE OR REPLACE TABLE stop_last AS
WITH tu AS (
    SELECT 'bus' AS grp, trip_id, start_date, route_id, stop_id,
           coalesce(nullif(vehicle_id, ''), trip_id) AS unit,
           coalesce(arrival_time, departure_time) AS predicted, feed_timestamp
    FROM read_parquet($bus_tu)
    UNION ALL
    -- NYCT trip ids start with the origin time in hundredths of a minute ('150700' = 25:07), and
    -- a trip that starts after midnight carries the calendar date as start_date, not its service
    -- day: move it back one day so it matches the timetable of the day it belongs to.
    SELECT 'subway', trip_id,
           CASE WHEN TRY_CAST(split_part(trip_id, '_', 1) AS INT) >= 144000
                THEN strftime(try_strptime(start_date, '%Y%m%d') - INTERVAL 1 DAY, '%Y%m%d')
                ELSE start_date END,
           route_id, stop_id,
           coalesce(nullif(vehicle_id, ''), trip_id),
           coalesce(arrival_time, departure_time), feed_timestamp
    FROM read_parquet($subway_tu)
)
SELECT grp, trip_id, start_date AS service_date, unit, stop_id,
       min(route_id) AS rt_route_id,
       min(feed_timestamp)::BIGINT AS first_listed,
       max(feed_timestamp)::BIGINT AS last_listed,
       -- Latest snapshot wins; a duplicate row in that snapshot resolves to the later prediction.
       -- One numeric key (feed_timestamp, then predicted; epochs < 10^10) keeps this a cheap
       -- arg_max while making the choice fully deterministic.
       arg_max(predicted, feed_timestamp::HUGEINT * 10000000000 + predicted)::BIGINT
           AS last_prediction
FROM tu
-- A prediction must be a real epoch second (0 or absurd values would corrupt the arg_max key).
WHERE trip_id IS NOT NULL AND trip_id <> '' AND stop_id IS NOT NULL
  AND predicted > 0 AND predicted < 10000000000
  AND unit IS NOT NULL
  AND start_date IN (SELECT service_date FROM service_days)
GROUP BY ALL;

CREATE OR REPLACE TABLE trip_last AS
SELECT grp, trip_id, service_date, unit,
       max(last_listed) AS trip_last_listed,
       count(*) FILTER (WHERE last_listed = max_last) AS stops_in_last_snapshot
FROM (SELECT *, max(last_listed) OVER (PARTITION BY grp, trip_id, service_date, unit) AS max_last
      FROM stop_last)
GROUP BY ALL;

CREATE OR REPLACE TABLE observed_events AS
SELECT s.*,
       t.trip_last_listed,
       CASE
           WHEN s.last_listed < t.trip_last_listed
                AND s.last_prediction - s.last_listed > $max_lead_s THEN 'implausible'
           WHEN s.last_listed - s.last_prediction > $max_stale_s THEN 'stale'
           WHEN s.last_listed < t.trip_last_listed THEN 'passed'
           WHEN t.stops_in_last_snapshot = 1
                AND s.last_prediction <= t.trip_last_listed + $terminal_grace_s THEN 'terminal'
           ELSE 'unconfirmed'
       END AS status
FROM stop_last s
JOIN trip_last t USING (grp, trip_id, service_date, unit);

CREATE OR REPLACE TABLE event_status_summary AS
SELECT grp, service_date, status, count(*) AS events FROM observed_events GROUP BY ALL;

-- Feed-quality evidence (BR7): trips reported by more than one unit.
CREATE OR REPLACE TABLE multi_unit_summary AS
SELECT grp, service_date, count(*) AS rt_trips,
       count(*) FILTER (WHERE units > 1) AS multi_unit_trips,
       round(avg((units > 1)::INT), 4) AS multi_unit_share
FROM (SELECT grp, service_date, trip_id, count(DISTINCT unit) AS units
      FROM stop_last GROUP BY ALL)
GROUP BY ALL;
