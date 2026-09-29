-- Route delay percentiles (BR1). Exercises: aggregation, discrete percentiles.
SELECT grp, route_id, count(*) AS events,
       percentile_disc(0.5) WITHIN GROUP (ORDER BY delay_s) AS p50_delay_s,
       percentile_disc(0.9) WITHIN GROUP (ORDER BY delay_s) AS p90_delay_s
FROM stop_events
GROUP BY grp, route_id
