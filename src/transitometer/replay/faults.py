"""Seeded fault injection for robustness runs (never for KPI or acceptance results).

Faults rewrite the ordered stream of encoded snapshots of one feed:
  duplicates  each message is emitted twice with probability `duplicate_rate`
  lateness    a `late_share` of messages is held back and emitted with the first later snapshot
              at least `lateness_s` seconds newer (headers keep the original snapshot)
  outage      snapshots with feed timestamps in [start, start + duration) are dropped entirely
Only topics under the faults prefix may receive a faulted replay (run.check_topic_prefix).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from transitometer.replay.archive import EncodedSnapshot

# A message as it goes out: (key, value, snapshot it belongs to).
Outgoing = tuple[bytes, bytes, EncodedSnapshot]


@dataclass(frozen=True)
class Faults:
    seed: int = 0
    duplicate_rate: float = 0.0
    lateness_s: int = 0
    late_share: float = 0.0
    outage: tuple[int, int] | None = None  # (start epoch, duration s)

    @property
    def active(self) -> bool:
        return bool(self.duplicate_rate or (self.lateness_s and self.late_share) or self.outage)

    def label(self) -> str:
        parts = []
        if self.duplicate_rate:
            parts.append(f"dup{self.duplicate_rate:g}")
        if self.lateness_s and self.late_share:
            parts.append(f"late{self.lateness_s}s{self.late_share:g}")
        if self.outage:
            parts.append(f"outage{self.outage[0]}+{self.outage[1]}s")
        return "-".join(parts) or "none"


@dataclass
class _Held:
    release_at: int
    messages: list[Outgoing] = field(default_factory=list)


def _rng(seed: int, feed: str) -> random.Random:
    # Stable across processes and Python versions (unlike hash()).
    digest = hashlib.sha256(f"{seed}|{feed}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def apply(
    faults: Faults, feed: str, snapshots: Iterable[EncodedSnapshot]
) -> Iterator[tuple[EncodedSnapshot, list[Outgoing]]]:
    """Per snapshot actually emitted: the snapshot and the messages to send with it."""
    rng = _rng(faults.seed, feed)
    held: list[_Held] = []
    for snap in snapshots:
        if faults.outage and faults.outage[0] <= snap.feed_timestamp < sum(faults.outage):
            continue
        out: list[Outgoing] = []
        due = [h for h in held if h.release_at <= snap.feed_timestamp]
        held = [h for h in held if h.release_at > snap.feed_timestamp]
        for h in due:
            out.extend(h.messages)
        late = _Held(snap.feed_timestamp + faults.lateness_s)
        for key, value in snap.messages:
            message = (key, value, snap)
            if faults.lateness_s and faults.late_share and rng.random() < faults.late_share:
                late.messages.append(message)
                continue
            out.append(message)
            if faults.duplicate_rate and rng.random() < faults.duplicate_rate:
                out.append(message)
        if late.messages:
            held.append(late)
        yield snap, out
    # Anything still held at the end of the replay is lost, as it would be in a real outage.
