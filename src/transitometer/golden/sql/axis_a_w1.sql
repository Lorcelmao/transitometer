-- Axis A W1: 1-minute tumbling event-time windows of arrival delay per (route, stop).
-- Event time is the observed arrival; a window [t, t + 60) holds the passages with a delay.
-- Windows without any delay are not produced (a streaming aggregation emits none either).
-- Reads only axis_a_passages, the exact input both engines receive.

CREATE OR REPLACE TABLE axis_a_w1 AS
SELECT grp, service_date, route_id, stop_id,
       (observed_arrival // 60) * 60 AS window_start,
       count(*) AS delays,
       sum(delay_s) AS delay_sum_s,
       avg(delay_s) AS mean_delay_s,
       min(delay_s) AS min_delay_s,
       max(delay_s) AS max_delay_s,
       stddev_pop(delay_s) AS stddev_delay_s
FROM axis_a_passages
WHERE delay_s IS NOT NULL
GROUP BY ALL;
