-- On time by mode day (BR1). Exercises: aggregation.
SELECT grp, service_date, count(*) AS events,
       round(sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS on_time_share
FROM stop_events
GROUP BY grp, service_date
