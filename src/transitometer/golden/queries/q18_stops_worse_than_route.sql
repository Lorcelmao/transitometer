-- Stops worse than route (BR5 x BR8). Exercises: join of aggregates.
SELECT s.grp, s.route_id, s.stop_id, s.events,
       round(s.on_time * 1.0 / s.events, 4) AS stop_on_time_share, r.on_time_share AS route_on_time_share
FROM (SELECT grp, route_id, stop_id, sum(events) AS events, sum(on_time) AS on_time
      FROM stop_hour_reliability GROUP BY grp, route_id, stop_id) s
JOIN route_scorecard r ON r.grp = s.grp AND r.route_id = s.route_id
WHERE s.events >= 30 AND s.on_time * 1.0 / s.events < r.on_time_share - 0.2
