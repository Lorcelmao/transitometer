-- BR5 reliability scorecards with uncertainty, and BR8 stop-level departure reliability.
-- Both pool the golden window (more events per cell); the statistic is the on-time share of KPI
-- events (same band as BR1).
--
-- Route and route-hour: stops of one trip are correlated, so the resampling unit is the trip.
-- Poisson bootstrap: in resample b every trip gets weight ~ Poisson(1), drawn from
--   u = first 8 hex digits of md5('$bootstrap_seed|b|grp|service_date|static_trip_id') (0..2^32-1)
-- against the Poisson(1) CDF scaled to 2^32 (floor(F(k) * 2^32), k = 0..7). The weights depend
-- only on that string, so any engine with md5 reproduces them exactly. Weighted counts are
-- integers, so every resampled share is exact and the run is deterministic.
-- CI = 2.5 / 97.5 % quantiles of the $bootstrap_resamples resampled shares. Routes are ranked by
-- on-time share (1 = best) and the rank interval comes from ranking within each resample.
--
-- Route-stop-hour (BR8, finest BR5 level): each event is a different trip, so the trip-level
-- resampling reduces to resampling events and the closed-form Wilson score interval (95 %) is
-- used. Trips at one stop and hour still share traffic, so the interval is optimistic.
-- Cells with fewer than $min_events events, and routes / route-hours with fewer than $min_trips
-- trips (the resampling unit: one trip gives a zero-width interval), are flagged insufficient;
-- only sufficient routes are ranked.

CREATE OR REPLACE MACRO poisson1(u) AS
    CASE WHEN u < 1580030168 THEN 0 WHEN u < 3160060337 THEN 1 WHEN u < 3950075421 THEN 2
         WHEN u < 4213413783 THEN 3 WHEN u < 4279248373 THEN 4 WHEN u < 4292415291 THEN 5
         WHEN u < 4294609777 THEN 6 WHEN u < 4294923276 THEN 7 ELSE 8 END;

CREATE OR REPLACE MACRO wilson(k, n, sign) AS
    ((k / n + 3.841458820694124 / (2 * n))
     + sign * 1.959963984540054
       * sqrt((k / n) * (1 - k / n) / n + 3.841458820694124 / (4 * n * n)))
    / (1 + 3.841458820694124 / n);

CREATE OR REPLACE TABLE scored_events AS
SELECT grp, service_date, static_trip_id, route_id, direction_id, stop_id, service_hour, delay_s,
       (otp_class(delay_s) = 'on_time')::INT AS on_time
FROM stop_events;

CREATE OR REPLACE TABLE bootstrap_weights AS
SELECT t.grp, t.service_date, t.static_trip_id, r.b,
       poisson1(('0x' || left(md5('$bootstrap_seed' || '|' || r.b || '|' || t.grp || '|'
                                  || t.service_date || '|' || t.static_trip_id), 8))::UBIGINT)
           AS w
FROM (SELECT DISTINCT grp, service_date, static_trip_id FROM scored_events) t
CROSS JOIN (SELECT range AS b FROM range(1, $bootstrap_resamples + 1)) r;

CREATE OR REPLACE TABLE route_scorecard AS
WITH per_trip AS (
    SELECT grp, route_id, service_date, static_trip_id,
           count(*) AS n, sum(on_time)::BIGINT AS k
    FROM scored_events GROUP BY ALL
),
point AS (
    SELECT grp, route_id, sum(n)::BIGINT AS events, count(*) AS trips, sum(k)::BIGINT AS on_time
    FROM per_trip GROUP BY ALL
),
resampled AS (
    SELECT p.grp, p.route_id, w.b, sum(w.w * p.k) / sum(w.w * p.n) AS share
    FROM per_trip p
    JOIN bootstrap_weights w USING (grp, service_date, static_trip_id)
    GROUP BY ALL HAVING sum(w.w * p.n) > 0
),
ranked AS (
    SELECT r.grp, r.route_id,
           rank() OVER (PARTITION BY r.grp, r.b ORDER BY r.share DESC) AS rank_b
    FROM resampled r JOIN point p USING (grp, route_id)
    WHERE p.events >= $min_events AND p.trips >= $min_trips
),
ci AS (
    SELECT grp, route_id, quantile_cont(share, 0.025) AS lo, quantile_cont(share, 0.975) AS hi
    FROM resampled GROUP BY ALL
),
rank_ci AS (
    SELECT grp, route_id, quantile_disc(rank_b, 0.025) AS rank_lo,
           quantile_disc(rank_b, 0.975) AS rank_hi
    FROM ranked GROUP BY ALL
)
SELECT p.grp, p.route_id, p.events, p.trips, p.on_time,
       round(p.on_time / p.events, 4) AS on_time_share,
       round(ci.lo, 4) AS ci_low, round(ci.hi, 4) AS ci_high,
       p.events >= $min_events AND p.trips >= $min_trips AS sufficient,
       CASE WHEN p.events >= $min_events AND p.trips >= $min_trips THEN rank() OVER (
           PARTITION BY p.grp, p.events >= $min_events AND p.trips >= $min_trips
           ORDER BY p.on_time / p.events DESC) END AS rank,
       rc.rank_lo AS rank_low, rc.rank_hi AS rank_high
FROM point p
LEFT JOIN ci USING (grp, route_id)
LEFT JOIN rank_ci rc USING (grp, route_id);

CREATE OR REPLACE TABLE route_hour_scorecard AS
WITH per_trip AS (
    SELECT grp, route_id, service_hour, service_date, static_trip_id,
           count(*) AS n, sum(on_time)::BIGINT AS k
    FROM scored_events GROUP BY ALL
),
resampled AS (
    SELECT p.grp, p.route_id, p.service_hour, w.b, sum(w.w * p.k) / sum(w.w * p.n) AS share
    FROM per_trip p
    JOIN bootstrap_weights w USING (grp, service_date, static_trip_id)
    GROUP BY ALL HAVING sum(w.w * p.n) > 0
)
SELECT p.grp, p.route_id, p.service_hour, sum(p.n)::BIGINT AS events, count(*) AS trips,
       round(sum(p.k) / sum(p.n), 4) AS on_time_share,
       round(any_value(c.lo), 4) AS ci_low, round(any_value(c.hi), 4) AS ci_high,
       sum(p.n) >= $min_events AND count(*) >= $min_trips AS sufficient
FROM per_trip p
LEFT JOIN (SELECT grp, route_id, service_hour, quantile_cont(share, 0.025) AS lo,
                  quantile_cont(share, 0.975) AS hi
           FROM resampled GROUP BY ALL) c USING (grp, route_id, service_hour)
GROUP BY ALL;

-- BR8: what a rider at this stop can expect from this route in this hour.
CREATE OR REPLACE TABLE stop_hour_reliability AS
SELECT grp, route_id, direction_id, stop_id, service_hour, count(*) AS events,
       sum(on_time)::BIGINT AS on_time,
       round(avg(on_time), 4) AS on_time_share,
       round(wilson(sum(on_time), count(*), -1), 4) AS ci_low,
       round(wilson(sum(on_time), count(*), 1), 4) AS ci_high,
       count(*) FILTER (WHERE otp_class(delay_s) = 'late') AS late,
       count(*) FILTER (WHERE otp_class(delay_s) = 'early') AS early,
       quantile_disc(delay_s, 0.5) AS p50_delay_s,
       quantile_disc(delay_s, 0.9) AS p90_delay_s,
       count(*) >= $min_events AS sufficient
FROM scored_events GROUP BY ALL;
