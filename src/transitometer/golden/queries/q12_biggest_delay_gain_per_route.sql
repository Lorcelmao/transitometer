-- Biggest delay gain per route (BR4). Exercises: window: LAG, then ROW_NUMBER.
SELECT grp, route_id, service_date, static_trip_id, unit, stop_id, gain_s
FROM (SELECT *, row_number() OVER (PARTITION BY grp, route_id
                                   ORDER BY gain_s DESC, service_date, static_trip_id, unit,
                                            stop_id) AS gain_rank
      FROM (SELECT grp, route_id, service_date, static_trip_id, unit, stop_id,
                   delay_s - lag(delay_s) OVER (PARTITION BY grp, service_date, static_trip_id, unit
                                                ORDER BY stop_sequence) AS gain_s
            FROM stop_events) g
      WHERE gain_s IS NOT NULL) r
WHERE gain_rank = 1
