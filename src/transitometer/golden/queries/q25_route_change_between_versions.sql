-- Route change between versions (BR1 x BR5). Exercises: time travel + join of two versions.
-- Time travel: Gold is loaded one service day per Delta commit, so the version holding only the
-- first service day is exactly `service_date = first day`. Delta engines read that version with
-- VERSION AS OF; the golden answer uses the equivalent filter. Engines without time travel
-- (ClickHouse) report this query as not applicable.
SELECT l.grp, l.route_id, f.on_time_share AS first_day_on_time_share,
       l.on_time_share AS latest_on_time_share,
       round(l.on_time_share - f.on_time_share, 4) AS change
FROM (SELECT grp, route_id, round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
      FROM stop_events WHERE service_date = (SELECT min(service_date) FROM stop_events)
      GROUP BY grp, route_id HAVING count(*) >= 100) f
JOIN (SELECT grp, route_id, round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
      FROM stop_events GROUP BY grp, route_id HAVING count(*) >= 100) l
  ON l.grp = f.grp AND l.route_id = f.route_id
