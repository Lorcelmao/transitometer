-- Route delay attribution (BR4). Exercises: aggregation of exact integer sums.
SELECT grp, route_id, count(*) AS trip_vehicles,
       round(sum(inherited_delay_s) * 1.0 / count(*), 2) AS mean_inherited_delay_s,
       round(sum(gained_delay_s) * 1.0 / count(*), 2) AS mean_gained_delay_s,
       round(sum(final_delay_s) * 1.0 / count(*), 2) AS mean_final_delay_s
FROM trip_delay_attribution
GROUP BY grp, route_id
