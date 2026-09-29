-- On time by delivery class (BR1 x BR3). Exercises: join.
SELECT e.grp, t.delivery, count(*) AS events,
       round(sum(CASE WHEN e.delay_s BETWEEN -60 AND 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4)
           AS on_time_share
FROM stop_events e
JOIN trip_delivery t
  ON t.grp = e.grp AND t.service_date = e.service_date AND t.trip_id = e.static_trip_id
GROUP BY e.grp, t.delivery
