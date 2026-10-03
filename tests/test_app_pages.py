"""Every Streamlit page renders without exceptions on each source the repository carries.

Needs the app extra (`pip install -e ".[app,dev]"`); the CI `app` job installs it. Pages are run
one function at a time (AppTest cannot switch between st.navigation function pages), plus the
entry script once for navigation and the snapshot banner.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("streamlit", reason="the app extra is not installed")

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from transitometer.serve import kpis  # noqa: E402

MAIN = kpis.REPO / "src" / "transitometer" / "app" / "main.py"
PAGES = [
    ("overview", "page"),
    ("reliability", "page_otp"),
    ("reliability", "page_headways"),
    ("reliability", "page_missing_trips"),
    ("scorecards", "page_route_scorecards"),
    ("scorecards", "page_stop_reliability"),
    ("diagnostics", "page_delay_attribution"),
    ("diagnostics", "page_early_warning"),
    ("quality", "page_feed_health"),
    ("quality", "page_validation"),
]


@pytest.fixture(params=["golden", "snapshot"])
def source(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    kind: str = request.param
    if kind == "snapshot" and not (kpis.SNAPSHOT_DIR / "manifest.json").exists():
        pytest.skip("no snapshot in showcase/data yet (python tasks.py snapshot)")
    monkeypatch.setenv("TRANSITOMETER_APP_SOURCE", kind)
    st.cache_resource.clear()  # the connection is cached per process, not per source
    return kind


@pytest.mark.parametrize(("module", "function"), PAGES)
def test_page_renders(source: str, module: str, function: str) -> None:
    app = AppTest.from_string(
        f"from transitometer.app import {module}\n{module}.{function}()", default_timeout=120
    )
    app.run()
    assert not app.exception, [e.value for e in app.exception]


def test_entry_script_shows_the_snapshot_banner_only_for_a_snapshot(source: str) -> None:
    app = AppTest.from_file(str(MAIN), default_timeout=120)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    banner = any("Snapshot of the Spark pipeline" in c.value for c in app.caption)
    assert banner is (source == "snapshot")


PARITY = kpis.REPO / "showcase" / "contract" / "parity-expected.json"
# Pages whose headline metrics are views' figures, with their filter widget prefix.
HEADLINES = [
    ("overview", "overview", "page", "overview"),
    ("headways", "reliability", "page_headways", "headways"),
    ("missing-trips", "reliability", "page_missing_trips", "missing"),
    ("delay", "diagnostics", "page_delay_attribution", "delay"),
]


@pytest.mark.parametrize(("view", "module", "function", "prefix"), HEADLINES)
@pytest.mark.parametrize("grp", ["bus", "subway"])
@pytest.mark.parametrize("day", ["20260922", "20260923"])
def test_headlines_equal_the_shared_parity_file(
    monkeypatch: pytest.MonkeyPatch,
    view: str,
    module: str,
    function: str,
    prefix: str,
    grp: str,
    day: str,
) -> None:
    """Streamlit shows the same headline strings the Next.js site is tested against."""
    if not PARITY.exists():
        pytest.skip("no parity file yet (python tasks.py web-data)")
    expected = json.loads(PARITY.read_text(encoding="utf-8"))[f"{view}/{grp}/{day}"]
    monkeypatch.setenv("TRANSITOMETER_APP_SOURCE", "snapshot")
    st.cache_resource.clear()
    app = AppTest.from_string(
        f"from transitometer.app import {module}\n{module}.{function}()", default_timeout=120
    )
    app.run()
    app.segmented_control(key=f"{prefix}-grp").set_value(grp)
    app.selectbox(key=f"{prefix}-day").set_value(day)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert [m.value for m in app.metric][: len(expected)] == [f["display"] for f in expected]
