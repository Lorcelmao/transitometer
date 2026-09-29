-- Follower delay by headway class (BR1 x BR2). Exercises: join.
SELECT h.grp, h.headway_class, count(*) AS headways,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY e.delay_s) AS p50_follower_delay_s
FROM headways h
JOIN stop_events e
  ON e.grp = h.grp AND e.service_date = h.service_date AND e.route_id = h.route_id
 AND e.stop_id = h.stop_id AND e.static_trip_id = h.trip_key
GROUP BY h.grp, h.headway_class
