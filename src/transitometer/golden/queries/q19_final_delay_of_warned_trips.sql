-- Final delay of warned trips (BR6 x BR4). Exercises: join.
SELECT w.grp, w.warn_late, count(*) AS trip_vehicles,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY a.final_delay_s) AS p50_final_delay_s,
       round(sum(CASE WHEN a.final_delay_s > 300 THEN 1 ELSE 0 END) * 1.0 / count(*), 4) AS late_share
FROM warning_decisions w
JOIN trip_delay_attribution a
  ON a.grp = w.grp AND a.service_date = w.service_date AND a.static_trip_id = w.static_trip_id
 AND a.unit = w.unit
GROUP BY w.grp, w.warn_late
