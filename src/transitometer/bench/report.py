"""Summaries and charts of the S10 benchmarks, computed only from the raw CSVs.

Reads results/benchmarks/*.csv and writes results/benchmarks/summary/*.csv (the tables the
README and docs/benchmark-results.md quote) and, when Altair is installed, Vega-Lite charts as
self-contained HTML under results/benchmarks/charts/. Run with `python tasks.py bench-report`.

Statistics follow docs/benchmark-fairness.md: a per-run figure is reported as the median over
runs with min and max; within a run, percentiles are over all samples of that run.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def _csv(folder: Path, name: str) -> str | None:
    path = folder / f"{name}.csv"
    return f"read_csv_auto('{path.as_posix()}', header = true)" if path.exists() else None


def _spread(column: str, alias: str) -> str:
    return (
        f"median({column}) AS {alias}_median, min({column}) AS {alias}_min, "
        f"max({column}) AS {alias}_max"
    )


def summaries(folder: Path) -> dict[str, str]:
    """name -> SQL of each summary table whose inputs exist."""
    q: dict[str, str] = {}
    base = _csv(folder, "axis_b_base_latency")
    optimized = _csv(folder, "axis_b_optimized_latency")
    zero = _csv(folder, "axis_b_zero_copy_latency")
    samples = " UNION ALL ".join(f"SELECT * FROM {s}" for s in (base, optimized, zero) if s)
    if samples:
        q["axis_b_query_latency"] = f"""
            WITH s AS ({samples})
            SELECT arm, layout, query,
                   median(seconds) FILTER (WHERE phase = 'cold') AS cold_median_s,
                   min(seconds) FILTER (WHERE phase = 'cold') AS cold_min_s,
                   max(seconds) FILTER (WHERE phase = 'cold') AS cold_max_s,
                   quantile_cont(seconds, 0.5) FILTER (WHERE phase = 'warm') AS warm_p50_s,
                   quantile_cont(seconds, 0.95) FILTER (WHERE phase = 'warm') AS warm_p95_s
            FROM s GROUP BY ALL ORDER BY layout, query, arm"""
        q["axis_b_suite"] = f"""
            WITH s AS ({samples}),
            per_run AS (
                SELECT arm, layout, run,
                       sum(seconds) FILTER (WHERE phase = 'cold') AS cold_s,
                       sum(seconds) FILTER (WHERE phase = 'warm') / 5 AS warm_pass_s,
                       count(DISTINCT query) AS queries
                FROM s GROUP BY ALL)
            SELECT arm, layout, any_value(queries) AS queries,
                   {_spread("cold_s", "cold_suite_s")}, {_spread("warm_pass_s", "warm_suite_s")}
            FROM per_run GROUP BY ALL ORDER BY layout, arm"""
    fresh = _csv(folder, "axis_b_freshness")
    if fresh:
        q["axis_b_freshness"] = f"""
            SELECT arm, {_spread("visible_s", "visible_s")}, median(load_s) AS load_median_s,
                   median(delta_commit_s) AS delta_commit_median_s, bool_and(ok) AS all_ok
            FROM {fresh} GROUP BY arm ORDER BY arm"""
    foot = _csv(folder, "axis_b_footprint")
    if foot:
        q["axis_b_footprint"] = f"""
            SELECT sum(rows) AS rows,
                   sum(delta_data_bytes + delta_log_bytes) AS delta_bytes,
                   sum(clickhouse_bytes_on_disk) AS clickhouse_bytes,
                   sum(clickhouse_uncompressed_bytes) AS raw_bytes,
                   round(sum(clickhouse_uncompressed_bytes) / sum(delta_data_bytes), 2)
                       AS delta_ratio,
                   round(sum(clickhouse_uncompressed_bytes) / sum(clickhouse_bytes_on_disk), 2)
                       AS clickhouse_ratio,
                   sum(delta_files) AS delta_files, sum(clickhouse_parts) AS clickhouse_parts
            FROM {foot}"""
    compaction = _csv(folder, "axis_b_compaction")
    if compaction:
        q["axis_b_compaction"] = f"""
            SELECT sum(files_before) AS files_before, sum(files_after) AS files_after,
                   sum(data_bytes_before) AS bytes_before, sum(data_bytes_after) AS bytes_after,
                   round(sum(optimize_s), 1) AS optimize_s
            FROM {compaction}"""
    for scenario in ("latency", "knee", "late", "dup", "recovery"):
        runs = _csv(folder, f"axis_a_{scenario}_runs")
        if not runs:
            continue
        q[f"axis_a_{scenario}"] = f"""
            SELECT engine, plan, rate, count(*) AS runs,
                   {_spread("w1_p50_ms", "w1_p50_ms")}, {_spread("w1_p95_ms", "w1_p95_ms")},
                   {_spread("w1_p99_ms", "w1_p99_ms")},
                   {_spread("w2_p50_ms", "w2_p50_ms")}, {_spread("w2_p95_ms", "w2_p95_ms")},
                   {_spread("w2_p99_ms", "w2_p99_ms")},
                   {_spread("w2_last_output_lag_ms", "w2_drain_ms")},
                   count(*) FILTER (WHERE sustained) AS sustained_runs,
                   median(w1_missing) AS w1_missing_median, median(w1_extra) AS w1_extra_median,
                   median(w1_mismatched) AS w1_mismatched_median,
                   median(w2_missing) AS w2_missing_median, median(w2_extra) AS w2_extra_median,
                   median(w2_mismatched) AS w2_mismatched_median,
                   count(*) FILTER (WHERE w1_equal_golden AND w2_equal_golden) AS runs_equal_golden,
                   median(w1_output_duplicates + w2_output_duplicates) AS output_dupes_median,
                   median(spark_dropped_by_watermark) AS spark_dropped_median,
                   {_spread("resume_ms", "resume_ms")},
                   {_spread("peak_memory_gib", "peak_memory_gib")},
                   median(rate_achieved) AS rate_achieved_median
            FROM {runs} GROUP BY ALL ORDER BY engine, plan, rate"""
    scaling = _csv(folder, "scaling_runs")
    if scaling:
        q["scaling"] = f"""
            SELECT days, any_value(messages_in) AS messages_in, any_value(rows_out) AS rows_out,
                   {_spread("seconds", "seconds")},
                   round(any_value(rows_out) / median(seconds)) AS rows_per_s_median
            FROM {scaling} GROUP BY days ORDER BY days"""
    return q


def write(folder: Path) -> dict[str, int]:
    """Write every summary table; returns name -> rows."""
    out = folder / "summary"
    out.mkdir(parents=True, exist_ok=True)
    written = {}
    with duckdb.connect() as con:
        for name, sql in summaries(folder).items():
            target = out / f"{name}.csv"
            con.execute(f"COPY ({sql}) TO '{target.as_posix()}' (HEADER, DELIMITER ',')")
            written[name] = int(con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0])  # type: ignore[index]
    charts(folder)
    return written


def charts(folder: Path) -> list[str]:
    """Vega-Lite charts (HTML) when Altair is installed; returns the files written."""
    try:
        import altair as alt
    except ImportError:
        return []
    out = folder / "charts"
    out.mkdir(exist_ok=True)
    made: list[str] = []
    with duckdb.connect() as con:
        summary = folder / "summary"

        def frame(sql: str):  # type: ignore[no-untyped-def]
            return con.execute(sql).df()

        if (summary / "axis_b_query_latency.csv").exists():
            per_query = (summary / "axis_b_query_latency.csv").as_posix()
            data = frame(f"SELECT * FROM read_csv_auto('{per_query}') WHERE layout = 'delta'")
            chart = (
                alt.Chart(data, title="Axis B: warm p50 per query (log scale)")
                .mark_bar()
                .encode(
                    x=alt.X("warm_p50_s:Q", scale=alt.Scale(type="log"), title="seconds"),
                    y=alt.Y("query:N", title=None),
                    yOffset="arm:N",
                    color="arm:N",
                )
            )
            chart.save(str(out / "axis_b_warm_p50.html"))
            made.append("axis_b_warm_p50.html")
        pct = folder / "axis_a_latency_percentiles.csv"
        if pct.exists():
            data = frame(
                f"SELECT engine, workload, percentile, median(latency_ms) / 1000 AS seconds "
                f"FROM read_csv_auto('{pct.as_posix()}') GROUP BY ALL"
            )
            chart = (
                alt.Chart(data, title="Axis A: latency distribution at 200 passages/s")
                .mark_line()
                .encode(
                    x=alt.X("seconds:Q", title="latency (s)"),
                    y=alt.Y("percentile:Q", title="percentile"),
                    color="engine:N",
                    strokeDash="workload:N",
                )
            )
            chart.save(str(out / "axis_a_latency_cdf.html"))
            made.append("axis_a_latency_cdf.html")
        knee = summary / "axis_a_knee.csv"
        if knee.exists():
            data = frame(f"SELECT * FROM read_csv_auto('{knee.as_posix()}')")
            chart = (
                alt.Chart(data, title="Axis A: W2 p95 latency vs input rate")
                .mark_line(point=True)
                .encode(
                    x=alt.X("rate:Q", scale=alt.Scale(type="log"), title="passages/s"),
                    y=alt.Y("w2_p95_ms_median:Q", scale=alt.Scale(type="log"), title="ms"),
                    color="engine:N",
                )
            )
            chart.save(str(out / "axis_a_knee.html"))
            made.append("axis_a_knee.html")
        scaling = summary / "scaling.csv"
        if scaling.exists():
            data = frame(f"SELECT * FROM read_csv_auto('{scaling.as_posix()}')")
            chart = (
                alt.Chart(data, title="Silver build time by real-data slice")
                .mark_line(point=True)
                .encode(x="days:Q", y=alt.Y("seconds_median:Q", title="seconds"))
            )
            chart.save(str(out / "scaling.html"))
            made.append("scaling.html")
    return made
