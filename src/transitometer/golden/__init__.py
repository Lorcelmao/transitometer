"""Golden reference KPIs: independent DuckDB SQL over the landing Parquet (IMPLEMENTATION_PLAN S4).

Every engine (Spark, Flink, serving arms) is graded against these results. The SQL reads the
archive files directly, so it is independent of Kafka, the protobuf re-encoding and Spark.
All times are integer epoch seconds; local-time logic uses the agency timezone inside DuckDB.
"""
