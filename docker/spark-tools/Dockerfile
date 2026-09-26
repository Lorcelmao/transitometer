# Spark + Delta + Kafka connector, plus the Python tooling (replay harness, DuckDB, Streamlit).
# One image serves the spark and app profiles to keep the image footprint small (§4.2).
# First built and verified in S2 (walking skeleton).
ARG SPARK_BASE_IMAGE
FROM ${SPARK_BASE_IMAGE}

ARG SPARK_VERSION
ARG DELTA_VERSION
ARG DELTA_SPARK_ARTIFACT
ARG SPARK_KAFKA_ARTIFACT
ARG SPARK_PROTOBUF_ARTIFACT
ARG GRPCIO_TOOLS_VERSION=1.84.0

USER root

# Resolve connector jars (with transitive dependencies) at build time so runs never download.
# install-jars.sh skips libraries Spark already ships and fails the build on any duplicate.
COPY install-jars.sh /tmp/install-jars.sh
RUN printf 'pass\n' > /tmp/noop.py \
 && /opt/spark/bin/spark-submit --conf spark.jars.ivy=/tmp/ivy \
      --packages "${DELTA_SPARK_ARTIFACT}:${DELTA_VERSION},${SPARK_KAFKA_ARTIFACT}:${SPARK_VERSION},${SPARK_PROTOBUF_ARTIFACT}:${SPARK_VERSION}" \
      /tmp/noop.py \
 && bash /tmp/install-jars.sh /tmp/ivy/jars \
 && rm -rf /tmp/ivy /tmp/noop.py /tmp/install-jars.sh

# requirements.lock pins every transitive package to the versions the skeleton was tested with.
# delta-spark's Python API only; PySpark itself comes from the base image, so skip its pyspark dependency.
COPY requirements.txt requirements.lock /tmp/
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements.txt -c /tmp/requirements.lock \
 && python3 -m pip install --no-cache-dir --no-deps "delta-spark==${DELTA_VERSION}"

# Compile the official GTFS-Realtime schema into a descriptor set for Spark's from_protobuf.
# The compiler is only needed here, so it is removed in the same layer (protobuf stays locked).
COPY gtfs-realtime.proto /opt/transitometer/proto/gtfs-realtime.proto
RUN python3 -m pip install --no-cache-dir "grpcio-tools==${GRPCIO_TOOLS_VERSION}" -c /tmp/requirements.lock \
 && python3 -m grpc_tools.protoc -I/opt/transitometer/proto --include_imports \
      --descriptor_set_out=/opt/transitometer/gtfs-realtime.desc gtfs-realtime.proto \
 && python3 -m pip uninstall -y grpcio-tools grpcio \
 && rm /tmp/requirements.txt /tmp/requirements.lock \
 && chmod a+r /opt/transitometer/gtfs-realtime.desc
ENV GTFS_RT_DESCRIPTOR=/opt/transitometer/gtfs-realtime.desc

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
