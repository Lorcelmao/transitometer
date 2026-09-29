-- Version first day vs latest (BR1). Exercises: time travel.
-- Time travel: Gold is loaded one service day per Delta commit, so the version holding only the
-- first service day is exactly `service_date = first day`. Delta engines read that version with
-- VERSION AS OF; the golden answer uses the equivalent filter. Engines without time travel
-- (ClickHouse) report this query as not applicable.
SELECT 'first_day_version' AS version, count(*) AS events,
       round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
FROM stop_events
WHERE service_date = (SELECT min(service_date) FROM stop_events)
UNION ALL
SELECT 'latest_version', count(*), round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4)
FROM stop_events
