-- Worst stops per route (BR8). Exercises: window: ROW_NUMBER top-N per group.
SELECT grp, route_id, stop_id, events, p50_delay_s, stop_rank
FROM (SELECT *, row_number() OVER (PARTITION BY grp, route_id
                                   ORDER BY p50_delay_s DESC, stop_id) AS stop_rank
      FROM (SELECT grp, route_id, stop_id, count(*) AS events,
                   percentile_disc(0.5) WITHIN GROUP (ORDER BY delay_s) AS p50_delay_s
            FROM stop_events GROUP BY grp, route_id, stop_id) s
      WHERE events >= 20) r
WHERE stop_rank <= 3
