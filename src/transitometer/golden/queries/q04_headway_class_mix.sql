-- Headway class mix (BR2). Exercises: aggregation, window over aggregate.
SELECT grp, service_date, headway_class, count(*) AS headways,
       round(count(*) * 1.0 / sum(count(*)) OVER (PARTITION BY grp, service_date), 4) AS share
FROM headways
GROUP BY grp, service_date, headway_class
