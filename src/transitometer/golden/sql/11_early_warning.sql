-- BR6 rule-based early warning, judged once per trip and vehicle, at a decision point.
-- Decision point: the first KPI event at or past the middle of the trip's scheduled stops
-- (position >= half the stop count) that is followed by at least one more KPI event of the same
-- vehicle, so the outcome is observed later and never feeds the warning. The inputs use only
-- stops at or before the decision stop; a stop event becomes known when the next snapshot no
-- longer lists the stop, which can be a few minutes after its arrival time (decision_time):
--   delay_s        current delay
--   trend          (delay_s - delay at the vehicle's first observed stop) / scheduled time between
--   projected      delay_s + $warn_trend_weight * trend * scheduled time still to go to the trip's
--                  last scheduled stop (the trend is damped: delay trends partly revert); the
--                  outcome is measured at the last observed stop, usually the last intermediate
--   headway_s      the trip's headway at the decision stop, against the scheduled reference
-- Warnings and their naive baselines:
--   late     rule: projected > $late_s                    baseline: delay_s > $late_s
--   bunched  rule: headway <= $warn_headway_ratio x ref       baseline: already bunched now
-- Outcomes: late = delay at the vehicle's last observed KPI stop > $late_s; bunched = the trip
-- is classified 'bunched' (as follower) at any later KPI stop.
-- The decision population itself uses whole-day knowledge (a later KPI event must exist, and KPI
-- events exclude ambiguous trip-stops), so absolute precision is optimistic for live use; the rule
-- and its baseline are judged on the same population, so their comparison is fair.
-- Rules and thresholds were fixed on the development day (the first golden day) only, from a small
-- sweep (trend weight 0.25 / 0.5 / 0.75 / 1 with minimum delays 0 / 60 / 120 s; headway ratio
-- 0.35 / 0.5 / 0.75, with and without a closing condition): 0.5 and 0.5 had the best F1 in the
-- grid for both bus and subway; the other day is held out. Acceptance, declared before
-- the held-out day was computed: on the held-out day the rule beats its baseline on F1 with
-- precision >= 0.6. Development day: bus late F1 0.785 vs 0.762 (precision 0.84), subway late
-- 0.622 vs 0.558 (0.68), bus bunched 0.640 vs 0.480 (0.79); subway bunched 0.278 vs 0.118 but
-- precision 0.23 (137 bunched outcomes in 2,520 trips): expected to miss the precision target.

CREATE OR REPLACE TABLE warning_inputs AS
WITH trip_len AS (
    SELECT grp, service_date, trip_id, max(pos) AS n_stops FROM sched_positions GROUP BY ALL
),
trip_end AS (
    SELECT grp, service_date, trip_id, max(sched_arrival) AS last_sched FROM scheduled_stops
    GROUP BY ALL
),
ev AS (
    SELECT e.grp, e.service_date, e.static_trip_id, e.unit, e.route_id, e.stop_id,
           e.stop_sequence, p.pos, l.n_stops, e.sched_arrival, e.observed_arrival, e.delay_s,
           x.last_sched, h.headway_s, h.ref_headway_s, h.headway_class
    FROM stop_events e
    JOIN sched_positions p
      ON p.grp = e.grp AND p.service_date = e.service_date AND p.trip_id = e.static_trip_id
     AND p.stop_sequence = e.stop_sequence
    JOIN trip_len l
      ON l.grp = e.grp AND l.service_date = e.service_date AND l.trip_id = e.static_trip_id
    JOIN trip_end x
      ON x.grp = e.grp AND x.service_date = e.service_date AND x.trip_id = e.static_trip_id
    LEFT JOIN headways h
      ON h.grp = e.grp AND h.service_date = e.service_date AND h.route_id = e.route_id
     AND h.stop_id = e.stop_id AND h.trip_key = e.static_trip_id
)
SELECT *,
       first_value(delay_s) OVER w AS first_delay,
       first_value(sched_arrival) OVER w AS first_sched,
       arg_max(delay_s, stop_sequence) OVER t AS final_delay,
       max(stop_sequence) OVER t AS last_observed_seq,
       -- bunched at a later KPI stop of this vehicle: bunched rows strictly after this one
       sum((headway_class = 'bunched')::INT) OVER (
           PARTITION BY grp, service_date, static_trip_id, unit ORDER BY stop_sequence
           ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING) AS later_bunched
FROM ev
WINDOW w AS (PARTITION BY grp, service_date, static_trip_id, unit ORDER BY stop_sequence),
       t AS (PARTITION BY grp, service_date, static_trip_id, unit);

CREATE OR REPLACE TABLE warning_decisions AS
WITH d AS (
    SELECT * FROM warning_inputs
    WHERE 2 * pos >= n_stops AND stop_sequence < last_observed_seq
    QUALIFY row_number() OVER (
        PARTITION BY grp, service_date, static_trip_id, unit ORDER BY stop_sequence) = 1
),
f AS (
    SELECT *,
           CASE WHEN sched_arrival > first_sched
                THEN (delay_s - first_delay) / (sched_arrival - first_sched) ELSE 0 END AS trend
    FROM d
)
SELECT grp, service_date, static_trip_id, unit, route_id, stop_id AS decision_stop,
       observed_arrival AS decision_time, delay_s, round(trend, 6) AS trend,
       round(delay_s + $warn_trend_weight * trend * (last_sched - sched_arrival))
           AS projected_delay_s,
       headway_s, ref_headway_s,
       delay_s + $warn_trend_weight * trend * (last_sched - sched_arrival) > $late_s AS warn_late,
       delay_s > $late_s AS baseline_late,
       final_delay > $late_s AS late,
       coalesce(headway_s <= $warn_headway_ratio * ref_headway_s, false) AS warn_bunched,
       coalesce(headway_class = 'bunched', false) AS baseline_bunched,
       coalesce(later_bunched, 0) > 0 AS bunched
FROM f;

CREATE OR REPLACE TABLE early_warning_summary AS
WITH scored AS (
    SELECT grp, service_date, 'late' AS outcome, 'rule' AS method, warn_late AS warned, late AS actual
    FROM warning_decisions
    UNION ALL
    SELECT grp, service_date, 'late', 'baseline', baseline_late, late FROM warning_decisions
    UNION ALL
    SELECT grp, service_date, 'bunched', 'rule', warn_bunched, bunched FROM warning_decisions
    UNION ALL
    SELECT grp, service_date, 'bunched', 'baseline', baseline_bunched, bunched
    FROM warning_decisions
),
counts AS (
    SELECT grp, service_date, outcome, method, count(*) AS decisions,
           count(*) FILTER (WHERE actual) AS positives,
           count(*) FILTER (WHERE warned AND actual) AS tp,
           count(*) FILTER (WHERE warned AND NOT actual) AS fp,
           count(*) FILTER (WHERE NOT warned AND actual) AS fn
    FROM scored GROUP BY ALL
)
SELECT *,
       round(tp / nullif(tp + fp, 0), 4) AS precision,
       round(tp / nullif(tp + fn, 0), 4) AS recall,
       round(2 * tp / nullif(2 * tp + fp + fn, 0), 4) AS f1
FROM counts;
