-- Missing trips and gaps (BR3 x BR2). Exercises: outer join of aggregates.
SELECT g.grp, CASE WHEN coalesce(m.not_delivered, 0) > 0 THEN 'with_missing' ELSE 'without_missing' END
           AS route_hours, count(*) AS route_hour_count, sum(g.gaps) AS gaps,
       round(sum(g.gaps) * 1.0 / count(*), 4) AS gaps_per_route_hour
FROM (SELECT grp, service_date, route_id, service_hour,
             sum(CASE WHEN headway_class = 'gap' THEN 1 ELSE 0 END) AS gaps
      FROM headways GROUP BY grp, service_date, route_id, service_hour) g
LEFT JOIN (SELECT grp, service_date, route_id, service_hour,
                  sum(CASE WHEN delivery IN ('missing', 'not_run') THEN 1 ELSE 0 END) AS not_delivered
           FROM trip_delivery GROUP BY grp, service_date, route_id, service_hour) m
  ON m.grp = g.grp AND m.service_date = g.service_date AND m.route_id = g.route_id
 AND m.service_hour = g.service_hour
GROUP BY g.grp, CASE WHEN coalesce(m.not_delivered, 0) > 0 THEN 'with_missing' ELSE 'without_missing' END
