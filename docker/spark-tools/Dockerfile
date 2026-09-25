# Spark + Delta + Kafka connector, plus the Python tooling (replay harness, DuckDB, Streamlit).
# One image serves the spark and app profiles to keep the image footprint small (§4.2).
# First built and verified in S2 (walking skeleton).
ARG SPARK_BASE_IMAGE
FROM ${SPARK_BASE_IMAGE}

ARG SPARK_VERSION
ARG DELTA_VERSION
ARG DELTA_SPARK_ARTIFACT
ARG SPARK_KAFKA_ARTIFACT

USER root

# Resolve connector jars (with transitive dependencies) at build time so runs never download.
RUN printf 'pass\n' > /tmp/noop.py \
 && /opt/spark/bin/spark-submit --conf spark.jars.ivy=/tmp/ivy \
      --packages "${DELTA_SPARK_ARTIFACT}:${DELTA_VERSION},${SPARK_KAFKA_ARTIFACT}:${SPARK_VERSION}" \
      /tmp/noop.py \
 && cp /tmp/ivy/jars/*.jar /opt/spark/jars/ \
 && rm -rf /tmp/ivy /tmp/noop.py

COPY requirements.txt /tmp/requirements.txt
# delta-spark's Python API only; PySpark itself comes from the base image, so skip its pyspark dependency.
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt \
 && python3 -m pip install --no-cache-dir --no-deps "delta-spark==${DELTA_VERSION}" \
 && rm /tmp/requirements.txt

# Pre-install DuckDB extensions so the app and golden checks work offline.
ENV TRANSITOMETER_DUCKDB_EXT_DIR=/opt/duckdb-extensions
RUN python3 -c "import duckdb, os; con = duckdb.connect(config={'extension_directory': os.environ['TRANSITOMETER_DUCKDB_EXT_DIR']}); con.install_extension('delta'); con.install_extension('spatial')" \
 && chmod -R a+rX /opt/duckdb-extensions

# Named-volume mount points must exist with the runtime user's ownership; Docker copies it
# into a fresh volume, otherwise the volumes come up root-owned and unwritable for `spark`.
RUN mkdir -p /data/lakehouse /data/checkpoints /data/scratch /data/landing \
 && chown -R spark:spark /data

ENV PYTHONPATH=/opt/transitometer/src
USER spark
