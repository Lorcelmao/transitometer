-- Map real-time trips to scheduled trips active on the same service day, in tiers:
--   exact            real-time trip_id == static trip_id (MTA Bus)
--   suffix           == static trip_id after its first "_" (NYCT subway)
--   route_direction  origin time + route + direction letter ("083250_1..S"), for subway ids
--                    whose path code differs or is missing (7 line, reroutes)
-- A key that maps to more than one active scheduled trip is ambiguous and left unmatched.
-- Several real-time trips may still map to one scheduled trip (e.g. an id that changes mid-run);
-- 04_otp.sql keeps one observed event per scheduled trip-stop, so none is counted twice.
-- Real-time trips matched by no tier are 'unscheduled' (added service); they are excluded from
-- schedule-based KPIs and reported separately.

CREATE OR REPLACE MACRO rd_key(id) AS
    split_part(id, '..', 1) || '..' || left(split_part(id, '..', 2), 1);

CREATE OR REPLACE TABLE rt_trips AS
SELECT DISTINCT grp, trip_id, service_date FROM observed_events;

CREATE OR REPLACE TABLE static_keys AS
SELECT grp, service_date, trip_id AS static_trip_id,
       trip_id AS exact_key,
       CASE WHEN strpos(trip_id, '_') > 0 THEN substr(trip_id, strpos(trip_id, '_') + 1) END
           AS suffix_key
FROM active_trips;

CREATE OR REPLACE TABLE matched_trips AS
WITH exact_unique AS (
    SELECT grp, service_date, exact_key, any_value(static_trip_id) AS static_trip_id
    FROM static_keys GROUP BY ALL HAVING count(*) = 1
),
exact AS (
    SELECT r.grp, r.trip_id, r.service_date, k.static_trip_id, 'exact' AS tier
    FROM rt_trips r
    JOIN exact_unique k
      ON k.grp = r.grp AND k.service_date = r.service_date AND k.exact_key = r.trip_id
),
suffix_unique AS (
    SELECT grp, service_date, suffix_key, any_value(static_trip_id) AS static_trip_id
    FROM static_keys WHERE suffix_key IS NOT NULL
    GROUP BY ALL HAVING count(*) = 1
),
suffix AS (
    SELECT r.grp, r.trip_id, r.service_date, u.static_trip_id, 'suffix' AS tier
    FROM (SELECT * FROM rt_trips ANTI JOIN exact USING (grp, trip_id, service_date)) r
    JOIN suffix_unique u
      ON u.grp = r.grp AND u.service_date = r.service_date AND u.suffix_key = r.trip_id
),
rd_unique AS (
    SELECT grp, service_date, rd_key(suffix_key) AS k, any_value(static_trip_id) AS static_trip_id
    FROM static_keys WHERE strpos(suffix_key, '..') > 0
    GROUP BY ALL HAVING count(*) = 1
),
route_direction AS (
    SELECT r.grp, r.trip_id, r.service_date, u.static_trip_id, 'route_direction' AS tier
    FROM (SELECT * FROM rt_trips
          ANTI JOIN exact USING (grp, trip_id, service_date)
          ANTI JOIN suffix USING (grp, trip_id, service_date)) r
    JOIN rd_unique u
      ON u.grp = r.grp AND u.service_date = r.service_date AND u.k = rd_key(r.trip_id)
    WHERE strpos(r.trip_id, '..') > 0
)
SELECT * FROM exact
UNION ALL SELECT * FROM suffix
UNION ALL SELECT * FROM route_direction;

CREATE OR REPLACE TABLE trip_match_summary AS
SELECT r.grp, r.service_date, coalesce(m.tier, 'unscheduled') AS tier, count(*) AS rt_trips
FROM rt_trips r
LEFT JOIN matched_trips m USING (grp, trip_id, service_date)
GROUP BY ALL;
