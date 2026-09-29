-- Route delay percent rank (BR5). Exercises: window: PERCENT_RANK.
SELECT grp, route_id, p50_delay_s,
       round(percent_rank() OVER (PARTITION BY grp ORDER BY p50_delay_s), 4) AS delay_percent_rank
FROM (SELECT grp, route_id, count(*) AS events,
             percentile_disc(0.5) WITHIN GROUP (ORDER BY delay_s) AS p50_delay_s
      FROM stop_events GROUP BY grp, route_id) r
WHERE events >= 100
