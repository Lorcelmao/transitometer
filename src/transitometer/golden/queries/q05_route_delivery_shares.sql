-- Route delivery shares (BR3). Exercises: conditional aggregation.
SELECT grp, route_id, count(*) AS scheduled,
       sum(CASE WHEN delivery = 'missing' THEN 1 ELSE 0 END) AS missing,
       sum(CASE WHEN delivery = 'not_run' THEN 1 ELSE 0 END) AS not_run,
       round(sum(CASE WHEN delivery IN ('missing', 'not_run') THEN 1 ELSE 0 END) * 1.0
             / nullif(sum(CASE WHEN delivery <> 'unknown' THEN 1 ELSE 0 END), 0), 4)
           AS not_delivered_share
FROM trip_delivery
GROUP BY grp, route_id
