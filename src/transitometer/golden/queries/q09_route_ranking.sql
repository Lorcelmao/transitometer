-- Route ranking (BR5). Exercises: window: RANK.
SELECT grp, route_id, events, on_time_share,
       rank() OVER (PARTITION BY grp ORDER BY on_time_share DESC) AS route_rank
FROM (SELECT grp, route_id, count(*) AS events,
             round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
      FROM stop_events GROUP BY grp, route_id) r
WHERE events >= 100
