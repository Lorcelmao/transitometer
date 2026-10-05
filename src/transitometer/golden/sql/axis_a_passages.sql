-- Axis A input: every passage the BR2 headway rule uses (05_headways.sql `passages`), enriched
-- with static or already-inferred values only, so a streaming engine needs no joins:
--   service_hour    hour of the passage within its service day (as in 05_headways.sql)
--   delay_s         arrival delay of a scheduled trip-stop (04_otp.sql trip_stop_events);
--                   NULL for unscheduled passages, which have no timetable
--   ref_headway_s   median scheduled headway at that stop in that hour (scheduled_headway_ref);
--                   NULL where the timetable gives none
-- Runs after golden steps 01-05.

CREATE OR REPLACE TABLE axis_a_passages AS
SELECT p.grp, p.service_date, p.route_id, p.stop_id,
       (p.observed_arrival - day_base(p.service_date)) // 3600 AS service_hour,
       p.trip_key, p.trip_id, p.unit, p.source, p.observed_arrival,
       t.delay_s, r.ref_headway_s
FROM passages p
LEFT JOIN trip_stop_events t
       ON t.grp = p.grp AND t.service_date = p.service_date
      AND t.static_trip_id = p.trip_key AND t.stop_id = p.stop_id
LEFT JOIN scheduled_headway_ref r
       ON r.grp = p.grp AND r.service_date = p.service_date AND r.route_id = p.route_id
      AND r.stop_id = p.stop_id
      AND r.service_hour = (p.observed_arrival - day_base(p.service_date)) // 3600;
