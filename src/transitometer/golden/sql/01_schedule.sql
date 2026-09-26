-- Scheduled stop times for every trip active on each golden service day.
-- GTFS times are "seconds after noon minus 12 h" of the service day in the agency timezone, so
-- times past 24:00:00 and DST changes are handled by construction.

CREATE OR REPLACE TABLE service_days AS
SELECT unnest($service_dates) AS service_date;  -- 'YYYYMMDD'

CREATE OR REPLACE MACRO day_base(d) AS
    epoch(make_timestamptz(CAST(left(d, 4) AS INT), CAST(substr(d, 5, 2) AS INT),
                           CAST(right(d, 2) AS INT), 12, 0, 0, '$timezone')
          - INTERVAL 12 HOUR)::BIGINT;

CREATE OR REPLACE MACRO gtfs_seconds(t) AS
    CAST(split_part(t, ':', 1) AS INT) * 3600
    + CAST(split_part(t, ':', 2) AS INT) * 60
    + CAST(split_part(t, ':', 3) AS INT);

CREATE OR REPLACE TABLE sched_calendar AS
SELECT 'bus' AS grp, * FROM read_parquet($bus_calendar, union_by_name = true)
UNION ALL BY NAME
SELECT 'subway' AS grp, * FROM read_parquet($subway_calendar, union_by_name = true);

CREATE OR REPLACE TABLE sched_calendar_dates AS
SELECT 'bus' AS grp, * FROM read_parquet($bus_calendar_dates, union_by_name = true)
UNION ALL BY NAME
SELECT 'subway' AS grp, * FROM read_parquet($subway_calendar_dates, union_by_name = true);

CREATE OR REPLACE TABLE active_services AS
(
    SELECT c.grp, d.service_date, CAST(c.service_id AS VARCHAR) AS service_id
    FROM sched_calendar c CROSS JOIN service_days d
    WHERE CAST(c.start_date AS VARCHAR) <= d.service_date
      AND CAST(c.end_date AS VARCHAR) >= d.service_date
      AND CAST(CASE dayofweek(strptime(d.service_date, '%Y%m%d'))
                   WHEN 0 THEN c.sunday WHEN 1 THEN c.monday WHEN 2 THEN c.tuesday
                   WHEN 3 THEN c.wednesday WHEN 4 THEN c.thursday WHEN 5 THEN c.friday
                   ELSE c.saturday END AS INT) = 1
    UNION
    SELECT cd.grp, d.service_date, CAST(cd.service_id AS VARCHAR)
    FROM sched_calendar_dates cd JOIN service_days d ON CAST(cd.date AS VARCHAR) = d.service_date
    WHERE CAST(cd.exception_type AS INT) = 1
)
EXCEPT
SELECT cd.grp, d.service_date, CAST(cd.service_id AS VARCHAR)
FROM sched_calendar_dates cd JOIN service_days d ON CAST(cd.date AS VARCHAR) = d.service_date
WHERE CAST(cd.exception_type AS INT) = 2;

CREATE OR REPLACE TABLE sched_trips AS
SELECT 'bus' AS grp, * FROM read_parquet($bus_trips, union_by_name = true)
UNION ALL BY NAME
SELECT 'subway' AS grp, * FROM read_parquet($subway_trips, union_by_name = true);

CREATE OR REPLACE TABLE active_trips AS
SELECT t.grp, s.service_date, CAST(t.trip_id AS VARCHAR) AS trip_id,
       CAST(t.route_id AS VARCHAR) AS route_id, CAST(t.direction_id AS INT) AS direction_id
FROM sched_trips t
JOIN active_services s ON s.grp = t.grp AND s.service_id = CAST(t.service_id AS VARCHAR);

CREATE OR REPLACE TABLE scheduled_stops AS
WITH st AS (
    SELECT 'bus' AS grp, trip_id, arrival_time, departure_time, stop_id, stop_sequence, timepoint
    FROM read_parquet($bus_stop_times, union_by_name = true)
    UNION ALL BY NAME
    SELECT 'subway' AS grp, trip_id, arrival_time, departure_time, stop_id, stop_sequence
    FROM read_parquet($subway_stop_times, union_by_name = true)
)
SELECT a.grp, a.service_date, a.trip_id, a.route_id, a.direction_id,
       CAST(st.stop_id AS VARCHAR) AS stop_id,
       CAST(st.stop_sequence AS INT) AS stop_sequence,
       coalesce(CAST(st.timepoint AS INT), 0) = 1 AS timepoint,
       day_base(a.service_date) + gtfs_seconds(coalesce(st.arrival_time, st.departure_time))
           AS sched_arrival
FROM st
JOIN active_trips a ON a.grp = st.grp AND a.trip_id = CAST(st.trip_id AS VARCHAR)
WHERE coalesce(st.arrival_time, st.departure_time) IS NOT NULL;
