-- First vs last delay (BR4). Exercises: window: FIRST_VALUE / LAST_VALUE.
SELECT grp, count(*) AS trip_vehicles,
       round(sum(CASE WHEN last_delay > first_delay THEN 1 ELSE 0 END) * 1.0 / count(*), 4)
           AS worsened_share,
       round(sum(last_delay - first_delay) * 1.0 / count(*), 2) AS mean_change_s
FROM (SELECT DISTINCT grp, service_date, static_trip_id, unit,
             first_value(delay_s) OVER w AS first_delay,
             last_value(delay_s) OVER w AS last_delay
      FROM stop_events
      WINDOW w AS (PARTITION BY grp, service_date, static_trip_id, unit ORDER BY stop_sequence
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)) t
GROUP BY grp
