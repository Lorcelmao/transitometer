-- Last stop vs last intermediate (BR1 terminals x BR4). Exercises: join.
SELECT t.grp, count(*) AS trips,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY t.delay_s - a.final_delay_s) AS p50_change_s,
       round(sum(CASE WHEN t.delay_s > a.final_delay_s THEN 1 ELSE 0 END) * 1.0 / count(*), 4)
           AS later_at_last_stop_share
FROM terminal_events t
JOIN trip_delay_attribution a
  ON a.grp = t.grp AND a.service_date = t.service_date AND a.static_trip_id = t.static_trip_id
 AND a.unit = t.unit
WHERE t.observations = 1
GROUP BY t.grp
