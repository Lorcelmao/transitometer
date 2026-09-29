-- Worst route hours (BR1). Exercises: aggregation, HAVING, ORDER BY + LIMIT.
SELECT grp, route_id, service_hour, count(*) AS events,
       round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
FROM stop_events
GROUP BY grp, route_id, service_hour
HAVING count(*) >= 50
ORDER BY on_time_share, grp, route_id, service_hour
LIMIT 20
