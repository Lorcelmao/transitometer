-- Failing feed checks (BR7). Exercises: filter.
SELECT feed, day, metric, value, threshold
FROM feed_quality_metrics
WHERE NOT passed
