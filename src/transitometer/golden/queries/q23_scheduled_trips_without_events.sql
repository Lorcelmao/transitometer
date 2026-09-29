-- Scheduled trips without events (BR3). Exercises: anti-join (NOT EXISTS).
SELECT t.grp, t.service_date, t.delivery, count(*) AS trips
FROM trip_delivery t
WHERE NOT EXISTS (SELECT 1 FROM stop_events e
                  WHERE e.grp = t.grp AND e.service_date = t.service_date
                    AND e.static_trip_id = t.trip_id)
GROUP BY t.grp, t.service_date, t.delivery
