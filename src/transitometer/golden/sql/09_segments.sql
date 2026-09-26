-- BR4 segment travel times and delay attribution.
-- A segment joins two consecutive observed KPI events of one scheduled trip recorded by the same
-- vehicle (in stop order). When a trip is handed to another vehicle mid-route, the two vehicles'
-- clocks and predictions do not line up, so no segment crosses the change:
--   observed_travel = arrival at the later stop - arrival at the earlier stop
--   sched_travel    = the same difference in the timetable
--   excess          = observed_travel - sched_travel (time gained against the timetable if < 0)
-- Arrivals are arrival-to-arrival, so a segment includes the dwell at its first stop: this feed
-- reports no departures or stopped-at status, so dwell and running time cannot be separated.
-- Attribution per trip and vehicle: delay at any observed stop = delay inherited at the first stop
-- the vehicle was observed at + the sum of the excesses of the segments before it (exact, integer
-- seconds). Segments with hops > 1 skip unobserved stops. Negative observed travel (1-2 % of
-- segments: a late prediction at the earlier stop) stays in the attribution so it sums exactly,
-- and is left out of the travel-time distribution.

CREATE OR REPLACE TABLE sched_positions AS
SELECT grp, service_date, trip_id, stop_sequence,
       row_number() OVER (PARTITION BY grp, service_date, trip_id ORDER BY stop_sequence) AS pos
FROM scheduled_stops;

CREATE OR REPLACE TABLE segments AS
WITH ev AS (
    SELECT e.grp, e.service_date, e.static_trip_id, e.unit, e.route_id, e.direction_id, e.stop_id,
           e.stop_sequence, p.pos, e.sched_arrival, e.observed_arrival, e.delay_s,
           e.service_hour
    FROM stop_events e
    JOIN sched_positions p
      ON p.grp = e.grp AND p.service_date = e.service_date AND p.trip_id = e.static_trip_id
     AND p.stop_sequence = e.stop_sequence
),
paired AS (
    SELECT *,
           lag(stop_id) OVER w AS from_stop,
           lag(pos) OVER w AS from_pos,
           lag(sched_arrival) OVER w AS from_sched,
           lag(observed_arrival) OVER w AS from_observed,
           lag(delay_s) OVER w AS from_delay,
           lag(service_hour) OVER w AS from_hour
    FROM ev
    WINDOW w AS (PARTITION BY grp, service_date, static_trip_id, unit ORDER BY stop_sequence)
)
SELECT grp, service_date, static_trip_id, unit, route_id, direction_id,
       from_stop, stop_id AS to_stop, pos - from_pos AS hops, from_hour AS service_hour,
       sched_arrival - from_sched AS sched_travel_s,
       observed_arrival - from_observed AS observed_travel_s,
       (observed_arrival - from_observed) - (sched_arrival - from_sched) AS excess_s,
       from_delay, delay_s AS to_delay
FROM paired WHERE from_stop IS NOT NULL;

CREATE OR REPLACE TABLE trip_delay_attribution AS
WITH ends AS (
    SELECT grp, service_date, static_trip_id, unit, any_value(route_id) AS route_id,
           count(*) AS observed_stops,
           arg_min(delay_s, stop_sequence) AS inherited_delay_s,
           arg_max(delay_s, stop_sequence) AS final_delay_s
    FROM stop_events GROUP BY ALL
),
gained AS (
    SELECT grp, service_date, static_trip_id, unit, sum(excess_s)::BIGINT AS gained_delay_s
    FROM segments GROUP BY ALL
)
SELECT e.*, coalesce(g.gained_delay_s, 0) AS gained_delay_s
FROM ends e LEFT JOIN gained g USING (grp, service_date, static_trip_id, unit);

CREATE OR REPLACE TABLE delay_attribution_summary AS
SELECT grp, service_date, count(*) AS trip_vehicles,
       round(avg(inherited_delay_s), 1) AS mean_inherited_delay_s,
       round(avg(gained_delay_s), 1) AS mean_gained_delay_s,
       round(avg(final_delay_s), 1) AS mean_final_delay_s,
       count(*) FILTER (WHERE final_delay_s <> inherited_delay_s + gained_delay_s)
           AS attribution_mismatches
FROM trip_delay_attribution GROUP BY ALL;

-- Travel-time distribution per adjacent segment and hour, pooled over the golden window.
CREATE OR REPLACE TABLE segment_travel_stats AS
SELECT grp, route_id, direction_id, from_stop, to_stop, service_hour, count(*) AS segments,
       median(sched_travel_s) AS sched_travel_s,
       quantile_disc(observed_travel_s, 0.1) AS p10_travel_s,
       quantile_disc(observed_travel_s, 0.5) AS p50_travel_s,
       quantile_disc(observed_travel_s, 0.9) AS p90_travel_s,
       quantile_disc(excess_s, 0.5) AS median_excess_s
FROM segments
WHERE hops = 1 AND observed_travel_s > 0
GROUP BY ALL;
