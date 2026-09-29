-- Bunching moving average (BR2). Exercises: window: moving frame.
SELECT grp, service_date, service_hour, headways, bunched_share,
       round(avg(bunched_share) OVER (PARTITION BY grp, service_date ORDER BY service_hour
                                      ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 4)
           AS bunched_share_3h
FROM (SELECT grp, service_date, service_hour, count(*) AS headways,
             round(sum(CASE WHEN headway_class = 'bunched' THEN 1 ELSE 0 END) * 1.0 / count(*), 6)
                 AS bunched_share
      FROM headways GROUP BY grp, service_date, service_hour) h
