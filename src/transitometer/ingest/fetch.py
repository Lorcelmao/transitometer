"""Download the source files into the landing zone and maintain data-manifest.json.

The committed manifest records URL, SHA-256, bytes, rows and licence per landing file. A fresh
machine re-fetching the same sources must reproduce identical checksums; a mismatch means the
archive changed upstream and is reported instead of silently accepted. A landing file is only
ever replaced by content that was accepted (matching checksum, new file, or --accept-changes).
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from transitometer.ingest.sources import FileSpec

CHUNK = 8 * 1024 * 1024
# Transient HTTP statuses worth retrying; other 4xx errors are permanent.
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
TRANSIENT_ERRORS = (
    urllib.error.URLError,
    http.client.IncompleteRead,
    ssl.SSLError,
    TimeoutError,
    ConnectionError,
)


@dataclass(frozen=True)
class ManifestEntry:
    url: str
    sha256: str
    bytes: int
    rows: int | None
    kind: str
    source: str
    license: str
    retrieved_utc: str


@dataclass
class FetchResult:
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_manifest(path: Path) -> dict[str, ManifestEntry]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {rel: ManifestEntry(**entry) for rel, entry in raw["files"].items()}


def save_manifest(path: Path, entries: dict[str, ManifestEntry]) -> None:
    """Atomically write sorted JSON, so an interruption never leaves a truncated manifest."""
    body = {"files": {rel: asdict(entries[rel]) for rel in sorted(entries)}}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def parquet_rows(path: Path) -> int | None:
    if path.suffix != ".parquet":
        return None
    rows: int = pq.ParquetFile(path).metadata.num_rows
    return rows


def download(url: str, dest: Path, retries: int = 3, backoff_s: float = 2.0) -> str:
    """Stream url into dest via a .part file; return the SHA-256 of the bytes written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(retries + 1):
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
                while chunk := response.read(CHUNK):
                    digest.update(chunk)
                    out.write(chunk)
            part.replace(dest)
            return digest.hexdigest()
        except urllib.error.HTTPError as exc:  # subclass of URLError: check it first
            part.unlink(missing_ok=True)
            if exc.code not in RETRYABLE_HTTP or attempt == retries:
                raise
        except TRANSIENT_ERRORS:
            part.unlink(missing_ok=True)
            if attempt == retries:
                raise
        time.sleep(backoff_s * 2**attempt)
    raise AssertionError("unreachable")


def fetch_one(
    spec: FileSpec,
    landing: Path,
    known: ManifestEntry | None,
    accept_changes: bool,
    downloader: Callable[[str, Path], str] = download,
) -> tuple[str, ManifestEntry | None]:
    """Return ("skipped" | "downloaded", new entry or None when nothing changed)."""
    dest = landing / spec.relpath
    unchanged = (
        dest.exists()
        and known is not None
        and dest.stat().st_size == known.bytes
        and sha256_file(dest) == known.sha256
    )
    if unchanged:
        return "skipped", None
    incoming = dest.with_name(dest.name + ".incoming")
    sha = downloader(spec.url, incoming)
    if known and sha != known.sha256 and not accept_changes:
        incoming.unlink(missing_ok=True)
        raise ValueError(
            f"upstream content changed (manifest {known.sha256[:12]}, got {sha[:12]}); "
            "rerun with --accept-changes to adopt it"
        )
    incoming.replace(dest)
    # Same content as recorded: keep the original retrieval time so the manifest stays stable.
    if known and sha == known.sha256:
        return "downloaded", known
    entry = ManifestEntry(
        url=spec.url,
        sha256=sha,
        bytes=dest.stat().st_size,
        rows=parquet_rows(dest),
        kind=spec.kind,
        source=spec.source,
        license=spec.license,
        retrieved_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    return "downloaded", entry


def fetch_all(
    specs: list[FileSpec],
    landing: Path,
    manifest_path: Path,
    workers: int = 4,
    accept_changes: bool = False,
    downloader: Callable[[str, Path], str] = download,
    progress: Callable[[str], None] = print,
) -> FetchResult:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    entries = load_manifest(manifest_path)
    result = FetchResult()
    pool = ThreadPoolExecutor(max_workers=workers)
    futures: dict[Future[tuple[str, ManifestEntry | None]], FileSpec] = {
        pool.submit(
            fetch_one, spec, landing, entries.get(spec.relpath), accept_changes, downloader
        ): spec
        for spec in specs
    }
    try:
        for future in as_completed(futures):
            spec = futures[future]
            try:
                status, entry = future.result()
            except Exception as exc:  # report every failure, keep fetching the rest
                result.errors[spec.relpath] = f"{type(exc).__name__}: {exc}"
                progress(f"FAILED  {spec.relpath}: {exc}")
                continue
            if entry is None:
                result.skipped.append(spec.relpath)
                continue
            entries[spec.relpath] = entry
            # Persist after every file (main thread only) so an interrupted fetch resumes cheaply.
            save_manifest(manifest_path, entries)
            result.downloaded.append(spec.relpath)
            progress(f"fetched {spec.relpath} ({entry.bytes / 1e6:.1f} MB)")
    except BaseException:
        # Ctrl+C or a crash: drop queued downloads instead of waiting for all of them.
        pool.shutdown(wait=False, cancel_futures=True)
        save_manifest(manifest_path, entries)
        raise
    pool.shutdown()
    save_manifest(manifest_path, entries)
    return result
