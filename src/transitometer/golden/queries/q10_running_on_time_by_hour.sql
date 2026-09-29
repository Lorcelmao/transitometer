-- Running on time by hour (BR1). Exercises: window: running sum.
SELECT grp, service_date, service_hour, events,
       round(sum(on_time) OVER w * 1.0 / sum(events) OVER w, 4) AS cumulative_on_time_share
FROM (SELECT grp, service_date, service_hour, count(*) AS events, sum(CASE WHEN delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) AS on_time
      FROM stop_events GROUP BY grp, service_date, service_hour) h
WINDOW w AS (PARTITION BY grp, service_date ORDER BY service_hour
             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
