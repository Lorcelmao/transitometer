"""Lakehouse layout shared by the Spark jobs and the app.

The kept real replay (topic prefix `rt`) owns the lakehouse root; any other prefix (the demo hour,
trials) gets its own subtree, so a demo run can never write into the tables the KPIs are checked on.
"""

from __future__ import annotations

KEPT_PREFIX = "rt"


def lakehouse_root(base: str, prefix: str) -> str:
    return base if prefix == KEPT_PREFIX else f"{base}/scratch/{prefix}"
