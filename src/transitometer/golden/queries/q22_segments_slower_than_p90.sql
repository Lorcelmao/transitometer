-- Segments slower than p90 (BR4). Exercises: join to a distribution table.
SELECT s.grp, count(*) AS segments,
       sum(CASE WHEN s.observed_travel_s > t.p90_travel_s THEN 1 ELSE 0 END) AS slower_than_p90,
       round(sum(CASE WHEN s.observed_travel_s > t.p90_travel_s THEN 1 ELSE 0 END) * 1.0 / count(*), 4)
           AS slower_share
FROM segments s
JOIN segment_travel_stats t
  ON t.grp = s.grp AND t.route_id = s.route_id AND t.direction_id = s.direction_id
 AND t.from_stop = s.from_stop AND t.to_stop = s.to_stop AND t.service_hour = s.service_hour
WHERE s.hops = 1 AND s.observed_travel_s > 0
GROUP BY s.grp
