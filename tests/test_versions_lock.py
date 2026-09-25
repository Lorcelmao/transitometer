from __future__ import annotations

from pathlib import Path

import pytest

from transitometer.ops.envfile import read_env_file
from transitometer.ops.versions_lock import pinned_images

VERSIONS_FILE = Path(__file__).resolve().parents[1] / "docker" / "versions.env"
DIGEST = "sha256:" + "a" * 64


def test_read_env_file_skips_comments_and_blanks(tmp_path: Path) -> None:
    env = tmp_path / "x.env"
    env.write_text("# comment\n\nA=1\n B = two words \nC=x=y\n", encoding="utf-8")
    assert read_env_file(env) == {"A": "1", "B": "two words", "C": "x=y"}


def test_read_env_file_rejects_malformed_line(tmp_path: Path) -> None:
    env = tmp_path / "x.env"
    env.write_text("JUSTAKEY\n", encoding="utf-8")
    with pytest.raises(ValueError, match=":1:"):
        read_env_file(env)


def test_pinned_images_requires_tag_and_digest() -> None:
    ok = pinned_images({"KAFKA_IMAGE": f"apache/kafka:4.3.1@{DIGEST}", "SPARK_VERSION": "4.1.3"})
    assert [(i.key, i.tag_ref, i.digest) for i in ok] == [
        ("KAFKA_IMAGE", "apache/kafka:4.3.1", DIGEST)
    ]
    with pytest.raises(ValueError):
        pinned_images({"KAFKA_IMAGE": "apache/kafka:4.3.1"})
    with pytest.raises(ValueError):
        pinned_images({"KAFKA_IMAGE": f"apache/kafka@{DIGEST}"})


def test_committed_lock_pins_every_image_and_version() -> None:
    values = read_env_file(VERSIONS_FILE)
    images = {i.key for i in pinned_images(values)}
    assert images == {"KAFKA_IMAGE", "SPARK_BASE_IMAGE", "FLINK_BASE_IMAGE", "CLICKHOUSE_IMAGE"}
    for key in (
        "SPARK_VERSION",
        "DELTA_VERSION",
        "PYFLINK_VERSION",
        "FLINK_KAFKA_CONNECTOR_VERSION",
    ):
        assert values[key], key
    # The Spark base image tag, the Kafka source artifact and the Delta artifact must agree.
    assert values["SPARK_BASE_IMAGE"].startswith(f"spark:{values['SPARK_VERSION']}-")
    spark_minor = ".".join(values["SPARK_VERSION"].split(".")[:2])
    assert values["DELTA_SPARK_ARTIFACT"].endswith(f"delta-spark_{spark_minor}_2.13")
    # Flink image, PyFlink and the connector's Flink suffix must agree.
    flink_minor = ".".join(values["PYFLINK_VERSION"].split(".")[:2])
    assert values["FLINK_BASE_IMAGE"].startswith(f"flink:{values['PYFLINK_VERSION']}-")
    assert values["FLINK_KAFKA_CONNECTOR_VERSION"].endswith(f"-{flink_minor}")
