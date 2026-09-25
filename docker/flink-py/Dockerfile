# Flink + PyFlink + Kafka SQL connector for the Axis A comparison workload only.
# Phase-scoped image: first built in S8 and removed after Axis A results are exported.
ARG FLINK_BASE_IMAGE
FROM ${FLINK_BASE_IMAGE}

ARG PYFLINK_VERSION
ARG FLINK_KAFKA_CONNECTOR_VERSION

USER root

# PyFlink in an isolated venv (base OS enforces PEP 668 for system pip).
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/pyflink-venv \
 && /opt/pyflink-venv/bin/pip install --no-cache-dir "apache-flink==${PYFLINK_VERSION}"

ADD --chown=flink:flink \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/${FLINK_KAFKA_CONNECTOR_VERSION}/flink-sql-connector-kafka-${FLINK_KAFKA_CONNECTOR_VERSION}.jar \
    /opt/flink/lib/

ENV PYTHONPATH=/opt/transitometer/src
USER flink
