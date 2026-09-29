"""Replay archived feeds into Kafka: the shared, deterministic input of every engine.

Usage (inside the Spark tooling image, landing mounted read-only):
  python -m transitometer.replay.run --days 2026-09-22 2026-09-23 [--speed 60] [--recreate]

Per feed, worker processes encode snapshots (one archive row group each) in parallel and one
producer sends them in archive order, so the same input yields the same messages at the same
offsets of fresh topics. Topics (prefix `rt` for real replays):
  <prefix>.<feed>             one protobuf FeedEntity per trip (key trip_id) or vehicle (key
                              vehicle_id); headers feed, feed_timestamp, fetch_timestamp_us,
                              source_file
  <prefix>.snapshots.<feed>   one JSON marker per feed snapshot, produced after its messages.
                              Markers are advisory (counts, lineage checks): a marker may become
                              readable before every message of its snapshot, so engines must not
                              treat it as "snapshot complete".
Pacing: a snapshot is sent at wall_start + (feed_timestamp - sim_start) / speed (0 = at once).
Lineage: per snapshot, the partition offset ranges its messages occupy (Parquet per feed).
Faulted replays (faults.py) may only write under the `faults` prefix.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import queue
import statistics
import sys
import time
import traceback
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from transitometer.replay import faults as faults_mod
from transitometer.replay.archive import FEEDS, EncodedSnapshot, Feed, encode_snapshot, row_groups

REAL_PREFIX = "rt"
FAULT_PREFIX = "faults"
PARTITIONS = 6
# Replay topics keep the whole replay (owner decision): engines read identical offsets. They are
# deleted after the engine phases; the storage guard runs before every replay.
TOPIC_CONFIG = {"retention.ms": "-1", "retention.bytes": "-1", "segment.bytes": str(64 << 20)}
PRODUCER_CONFIG = {
    "compression.type": "zstd",
    "linger.ms": 50,
    "batch.size": 1 << 20,
    "acks": "all",
    "enable.idempotence": True,  # retries never reorder or duplicate
    "partitioner": "murmur2_random",  # Java-client compatible key hashing
    "queue.buffering.max.messages": 200_000,  # bounded client memory (~100-200 MB per feed)
    "queue.buffering.max.kbytes": 262_144,
}
AHEAD_PER_WORKER = 2  # encoded snapshots waiting for the producer, per encoder
PROGRESS_EVERY_S = 30


def _progress(feed: str, done: int, total: int | None, elapsed: float) -> None:
    """One line on stderr (tasks.py echoes it live): snapshots done, rate, time left."""
    rate = done / elapsed if elapsed else 0.0
    if total:
        left = (total - done) / rate if rate else 0.0
        share = 100 * done / total
        line = f"{done}/{total} snapshots ({share:.0f}%), {rate:.1f}/s, ~{left / 60:.0f} min left"
    else:
        line = f"{done} snapshots, {rate:.1f}/s"
    print(f"progress replay {feed}: {line}", file=sys.stderr, flush=True)


def _optional(value: int | None) -> bytes:
    """Header value; empty when the archive has none (header order stays fixed)."""
    return b"" if value is None else str(value).encode()


def data_topic(prefix: str, feed: Feed) -> str:
    return f"{prefix}.{feed.name}"


def marker_topic(prefix: str, feed: Feed) -> str:
    return f"{prefix}.snapshots.{feed.name}"


def check_topic_prefix(prefix: str, faults: faults_mod.Faults) -> None:
    """Injected faults never reach the topics KPI and acceptance runs read."""
    if faults.active and prefix.split(".")[0] != FAULT_PREFIX:
        raise ValueError(f"a faulted replay must write under '{FAULT_PREFIX}', not '{prefix}'")
    if not faults.active and prefix.split(".")[0] == FAULT_PREFIX:
        raise ValueError(f"'{FAULT_PREFIX}' topics are reserved for faulted replays")


def archive_files(landing: Path, feed: Feed, days: list[date]) -> list[Path]:
    files = []
    for day in days:
        folder = landing / "realtime" / feed.kind / f"date={day:%Y-%m-%d}" / f"feed={feed.alias}"
        found = sorted(folder.glob("*.parquet"))
        if not found:
            raise FileNotFoundError(f"no archive for {feed.name} on {day}: {folder}")
        files.extend(found)
    return files


def first_timestamp(path: Path) -> int:
    column = pq.ParquetFile(path).read_row_group(0, columns=["feed_timestamp"])["feed_timestamp"]
    return int(column[0].as_py())


class Pacer:
    """Holds each snapshot until its scaled feed time; records how late it actually went out."""

    def __init__(
        self,
        speed: float,
        sim_start: int,
        wall_start: float,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.speed, self.sim_start, self.wall_start = speed, sim_start, wall_start
        self.clock, self.sleep = clock, sleep
        self.lags: list[float] = []

    def wait(self, feed_timestamp: int) -> None:
        if self.speed <= 0:
            return
        target = self.wall_start + (feed_timestamp - self.sim_start) / self.speed
        now = self.clock()
        if target > now:
            self.sleep(target - now)
            now = self.clock()
        self.lags.append(now - target)


def _encode(task: tuple[str, str, int]) -> EncodedSnapshot:
    return encode_snapshot(*task)


def encoded_snapshots(
    feed: Feed, files: list[Path], workers: int, until: int | None = None
) -> Iterator[EncodedSnapshot]:
    """Snapshots of the feed in archive order (before `until`, if set), encoded by a pool.

    At most AHEAD_PER_WORKER x workers snapshots are encoded ahead of the consumer, so a slow
    (paced or back-pressured) producer never makes encoded snapshots pile up in memory."""
    tasks = deque(
        (str(path), feed.kind, group) for path in files for group in row_groups(path, until)
    )
    with mp.get_context("spawn").Pool(workers) as pool:
        pending: deque[Any] = deque()
        last = -1
        while tasks or pending:
            while tasks and len(pending) < AHEAD_PER_WORKER * workers:
                pending.append(pool.apply_async(_encode, (tasks.popleft(),)))
            snap: EncodedSnapshot = pending.popleft().get()
            if snap.feed_timestamp < last:
                raise ValueError(f"{feed.name}: snapshot {snap.source_file} goes back in time")
            last = snap.feed_timestamp
            yield snap


def ensure_topics(bootstrap: str, topics: dict[str, int], recreate: bool) -> None:
    """Fresh topics (--recreate) or existing empty ones with the replay's configuration."""
    from confluent_kafka import Consumer, TopicPartition
    from confluent_kafka.admin import AdminClient, ConfigResource, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    present = [t for t in topics if t in admin.list_topics(timeout=30).topics]
    if present and recreate:
        for future in admin.delete_topics(present, operation_timeout=60).values():
            future.result(timeout=60)
        for _ in range(60):  # deletion is asynchronous
            if not set(present) & set(admin.list_topics(timeout=30).topics):
                break
            time.sleep(1)
    elif present:
        consumer = Consumer({"bootstrap.servers": bootstrap, "group.id": "replay-check"})
        try:
            for topic in present:
                meta = admin.list_topics(topic, timeout=30).topics[topic]
                if len(meta.partitions) != topics[topic]:
                    raise RuntimeError(f"{topic} has {len(meta.partitions)} partitions")
                for p in meta.partitions:
                    low, high = consumer.get_watermark_offsets(TopicPartition(topic, p), timeout=30)
                    if high > low:
                        raise RuntimeError(f"{topic} holds data; use --recreate for a fresh replay")
                resource = ConfigResource(ConfigResource.Type.TOPIC, topic)
                config = admin.describe_configs([resource])[resource].result(timeout=30)
                for name, value in TOPIC_CONFIG.items():
                    if config[name].value != value:  # e.g. auto-created with broker defaults
                        raise RuntimeError(
                            f"{topic}: {name}={config[name].value}, expected {value}"
                        )
        finally:
            consumer.close()
    missing = [t for t in topics if t not in admin.list_topics(timeout=30).topics]
    if missing:
        futures = admin.create_topics(
            [NewTopic(t, num_partitions=topics[t], config=TOPIC_CONFIG) for t in missing]
        )
        for future in futures.values():
            future.result(timeout=60)


@dataclass
class FeedReport:
    feed: str
    topic: str
    faults: str
    snapshots: int = 0
    rows: int = 0
    messages: int = 0
    acknowledged: int = 0
    payload_bytes: int = 0
    max_message_bytes: int = 0
    elapsed_s: float = 0.0
    pacing_lag_p50_s: float | None = None
    pacing_lag_p99_s: float | None = None
    pacing_lag_max_s: float | None = None


def replay_feed(
    feed: Feed,
    snapshots: Iterator[EncodedSnapshot],
    producer: Any,
    prefix: str,
    pacer: Pacer,
    faults: faults_mod.Faults,
    lineage_path: Path | None,
    total: int | None = None,
) -> FeedReport:
    """Send the feed's snapshots in order; `producer` is a confluent_kafka.Producer (or a stand-in
    with produce/poll/flush). Lineage attributes every message to the snapshot it came from."""
    check_topic_prefix(prefix, faults)
    if lineage_path is not None:
        lineage_path.unlink(missing_ok=True)  # never leave lineage of an earlier replay behind
    topic, markers = data_topic(prefix, feed), marker_topic(prefix, feed)
    report = FeedReport(feed.name, topic, faults.label())
    failures: list[str] = []
    # (origin snapshot index, partition) -> [first offset, last offset, messages]
    lineage: dict[tuple[int, int], list[int]] = {}
    seen: list[EncodedSnapshot] = []
    index_of: dict[int, int] = {}

    def delivered(index: int) -> Callable[[Any, Any], None]:
        def callback(error: Any, message: Any) -> None:
            if error is not None:
                failures.append(str(error))
                return
            report.acknowledged += 1
            if message.topic() == topic:
                span = lineage.setdefault((index, message.partition()), [message.offset(), 0, 0])
                span[0] = min(span[0], message.offset())
                span[1] = max(span[1], message.offset())
                span[2] += 1

        return callback

    def send(
        target: str, key: bytes, value: bytes, headers: list[tuple[str, bytes]], cb: Any
    ) -> None:
        while True:
            try:
                producer.produce(target, value=value, key=key, headers=headers, on_delivery=cb)
                return
            except BufferError:  # local queue full: let the client drain, then retry
                producer.poll(0.5)

    started = time.perf_counter()
    reported = started
    callbacks: dict[int, Callable[[Any, Any], None]] = {}
    for snap, outgoing in faults_mod.apply(faults, feed.name, snapshots):
        for origin in (snap, *(o for _, _, o in outgoing)):
            if id(origin) not in index_of:
                index_of[id(origin)] = len(seen)
                seen.append(origin)
                callbacks[index_of[id(origin)]] = delivered(index_of[id(origin)])
        pacer.wait(snap.feed_timestamp)
        for key, value, origin in outgoing:
            headers = [
                ("feed", feed.name.encode()),
                ("feed_timestamp", str(origin.feed_timestamp).encode()),
                ("fetch_timestamp_us", _optional(origin.fetch_timestamp_us)),
                ("source_file", origin.source_file.encode()),
            ]
            send(topic, key, value, headers, callbacks[index_of[id(origin)]])
            report.messages += 1
            report.payload_bytes += len(value)
            report.max_message_bytes = max(report.max_message_bytes, len(value))
        marker = {
            "feed": feed.name,
            "source_file": snap.source_file,
            "feed_timestamp": snap.feed_timestamp,
            "fetch_timestamp_us": snap.fetch_timestamp_us,
            "entities": len(outgoing),
            "rows": snap.rows,
        }
        send(
            markers,
            feed.name.encode(),
            json.dumps(marker).encode(),
            [],
            callbacks[index_of[id(snap)]],
        )
        report.messages += 1
        report.snapshots += 1
        report.rows += snap.rows
        snap.messages.clear()  # free the payloads; the snapshot's identity stays for lineage
        producer.poll(0)
        if time.perf_counter() - reported >= PROGRESS_EVERY_S:
            reported = time.perf_counter()
            _progress(feed.name, report.snapshots, total, reported - started)
        if failures:  # fail now, not hours later at the final flush
            raise RuntimeError(f"{feed.name}: delivery failed: {failures[:3]}")
    unsent = producer.flush(300)
    report.elapsed_s = round(time.perf_counter() - started, 1)
    if unsent or failures or report.acknowledged != report.messages:
        raise RuntimeError(
            f"{feed.name}: sent {report.messages}, acknowledged {report.acknowledged}, "
            f"still queued {unsent}, errors {failures[:3]}"
        )
    if pacer.lags:
        lags = sorted(pacer.lags)
        report.pacing_lag_p50_s = round(statistics.median(lags), 4)
        report.pacing_lag_p99_s = round(lags[min(len(lags) - 1, int(0.99 * len(lags)))], 4)
        report.pacing_lag_max_s = round(lags[-1], 4)
    if lineage_path is not None:
        write_lineage(lineage_path, feed.name, seen, lineage)
    return report


def write_lineage(
    path: Path,
    feed: str,
    snapshots: list[EncodedSnapshot],
    lineage: dict[tuple[int, int], list[int]],
) -> None:
    rows = sorted(lineage.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "feed": [feed] * len(rows),
                "source_file": [snapshots[i].source_file for (i, _), _ in rows],
                "archive_path": [snapshots[i].path for (i, _), _ in rows],
                "row_group": pa.array([snapshots[i].row_group for (i, _), _ in rows], pa.int32()),
                "feed_timestamp": [snapshots[i].feed_timestamp for (i, _), _ in rows],
                "partition": pa.array([p for (_, p), _ in rows], pa.int32()),
                "first_offset": [span[0] for _, span in rows],
                "last_offset": [span[1] for _, span in rows],
                "messages": [span[2] for _, span in rows],
            }
        ),
        path,
    )


def _feed_process(args: dict[str, Any], out: Any) -> None:
    """One feed's replay; always reports back, with the error if it failed."""
    try:
        from confluent_kafka import Producer

        feed = next(f for f in FEEDS if f.name == args["feed"])
        files = [Path(p) for p in args["files"]]
        total = sum(len(row_groups(path, args["until"])) for path in files)
        producer = Producer({"bootstrap.servers": args["bootstrap"], **PRODUCER_CONFIG})
        report = replay_feed(
            feed,
            encoded_snapshots(feed, files, args["workers"], args["until"]),
            producer,
            args["prefix"],
            Pacer(args["speed"], args["sim_start"], args["wall_start"]),
            faults_mod.Faults(**args["faults"]),
            Path(args["lineage_dir"]) / f"{feed.name}.parquet" if args["lineage_dir"] else None,
            total,
        )
        out.put(asdict(report))
    except BaseException:
        out.put({"feed": args["feed"], "error": traceback.format_exc()[-3000:]})
        raise


def run(args: argparse.Namespace) -> dict[str, Any]:
    faults = faults_mod.Faults(
        seed=args.seed,
        duplicate_rate=args.duplicate_rate,
        lateness_s=args.lateness,
        late_share=args.late_share,
        outage=(args.outage_start, args.outage_duration) if args.outage_duration else None,
    )
    check_topic_prefix(args.prefix, faults)
    feeds = [f for f in FEEDS if not args.feeds or f.name in args.feeds]
    days = [date.fromisoformat(d) for d in args.days]
    files = {f.name: archive_files(Path(args.landing), f, days) for f in feeds}
    topics = {data_topic(args.prefix, f): PARTITIONS for f in feeds}
    topics |= {marker_topic(args.prefix, f): 1 for f in feeds}
    ensure_topics(args.bootstrap, topics, args.recreate)
    # The clock origin comes from every feed, so a subset replay paces like a full one.
    all_files = {f.name: archive_files(Path(args.landing), f, days) for f in FEEDS}
    sim_start = min(first_timestamp(paths[0]) for paths in all_files.values())
    until = sim_start + int(args.minutes * 60) if args.minutes else None
    wall_start = time.time() + 5  # every feed process shares one clock origin
    workers = {
        "trip_updates.bus": args.workers,
        "trip_updates.subway": 1,
        "vehicle_positions.bus": 1,
    }
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    processes = []
    for feed in feeds:
        spec = {
            "feed": feed.name,
            "files": [str(p) for p in files[feed.name]],
            "bootstrap": args.bootstrap,
            "prefix": args.prefix,
            "workers": workers[feed.name],
            "speed": args.speed,
            "sim_start": sim_start,
            "wall_start": wall_start,
            "faults": asdict(faults),
            "lineage_dir": args.lineage_dir,
            "until": until,
        }
        process = ctx.Process(target=_feed_process, args=(spec, out))
        process.start()
        processes.append(process)
    reports: list[dict[str, Any]] = []
    try:
        while len(reports) < len(processes):
            try:
                result = out.get(timeout=10)
            except queue.Empty:
                crashed = [p for p in processes if p.exitcode not in (None, 0)]
                if crashed and out.empty():  # killed without reporting (e.g. out of memory)
                    raise RuntimeError(f"a feed replay died (exit {crashed[0].exitcode})") from None
                continue
            if "error" in result:
                raise RuntimeError(f"{result['feed']} replay failed:\n{result['error']}")
            reports.append(result)
    finally:
        for process in processes:
            if process.is_alive() and len(reports) < len(processes):
                process.terminate()
            process.join()
    return {
        "prefix": args.prefix,
        "days": args.days,
        "speed": args.speed,
        "minutes": args.minutes,
        "faults": faults.label(),
        "feeds": sorted(reports, key=lambda r: str(r["feed"])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--days", nargs="+", required=True, help="UTC archive days, YYYY-MM-DD")
    parser.add_argument("--feeds", nargs="*", help="subset of " + ", ".join(f.name for f in FEEDS))
    parser.add_argument("--prefix", default=REAL_PREFIX)
    parser.add_argument(
        "--speed", type=float, default=0.0, help="x real time; 0 = as fast as possible"
    )
    parser.add_argument("--workers", type=int, default=5, help="encoders for bus trip updates")
    parser.add_argument("--recreate", action="store_true", help="delete and recreate the topics")
    parser.add_argument("--minutes", type=float, default=0, help="only the first N minutes")
    parser.add_argument("--landing", default="/data/landing")
    parser.add_argument("--bootstrap", default="kafka:9092")
    parser.add_argument("--lineage-dir", default="/data/lakehouse/meta/replay_lineage")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--duplicate-rate", type=float, default=0.0)
    parser.add_argument("--lateness", type=int, default=0, choices=(0, 30, 120))
    parser.add_argument("--late-share", type=float, default=0.0)
    parser.add_argument("--outage-start", type=int, default=0, help="epoch seconds")
    parser.add_argument("--outage-duration", type=int, default=0, help="seconds")
    args = parser.parse_args(argv)
    if args.lineage_dir:
        args.lineage_dir = f"{args.lineage_dir}/{args.prefix}"
    print(json.dumps(run(args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
