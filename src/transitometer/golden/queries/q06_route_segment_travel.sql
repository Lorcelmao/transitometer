-- Route segment travel (BR4). Exercises: filtered aggregation, discrete percentiles.
SELECT grp, route_id, count(*) AS segments,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY observed_travel_s) AS p50_travel_s,
       percentile_disc(0.9) WITHIN GROUP (ORDER BY observed_travel_s) AS p90_travel_s
FROM segments
WHERE hops = 1 AND observed_travel_s > 0
GROUP BY grp, route_id
