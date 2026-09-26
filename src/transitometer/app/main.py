"""Walking-skeleton view: proves Delta -> DuckDB -> Streamlit end to end on one real hour."""

from __future__ import annotations

import glob
import os

import duckdb
import streamlit as st

from transitometer.serve import lakehouse

TABLE = os.path.join(
    os.environ.get("LAKEHOUSE_DIR", "/data/lakehouse"), "silver", "skeleton_vehicle_positions"
)


def table_committed(path: str) -> bool:
    """A Delta table is readable once its first commit file exists (not merely _delta_log/)."""
    return bool(glob.glob(os.path.join(path, "_delta_log", "*.json")))


st.set_page_config(page_title="Transitometer skeleton", layout="wide")
st.title("Transitometer — walking skeleton")
st.caption("Real MTA Bus vehicle positions replayed through Kafka → Spark → Delta → DuckDB.")

if not table_committed(TABLE):
    st.warning("No skeleton table yet. Run `python tasks.py skeleton` first.")
    st.stop()

try:
    with lakehouse.connect() as con:
        info = lakehouse.summary(con, TABLE)
        per_minute = lakehouse.vehicles_per_minute(con, TABLE)
        positions = lakehouse.latest_positions(con, TABLE)
except duckdb.Error as exc:  # e.g. the skeleton is rewriting the table right now
    st.warning(f"The skeleton table is being rewritten; reload in a moment. ({exc})")
    st.stop()

left, middle, right = st.columns(3)
left.metric("Silver rows", f"{info['rows']:,}")
middle.metric("Distinct vehicles", f"{info['vehicles']:,}")
right.metric("Minutes covered", len(per_minute))

st.subheader("Vehicles reporting per minute (feed time, UTC)")
st.line_chart(
    {"minute": [m for m, _ in per_minute], "vehicles": [v for _, v in per_minute]},
    x="minute",
    y="vehicles",
)

st.subheader("Latest snapshot positions")
st.map({"lat": [p[0] for p in positions], "lon": [p[1] for p in positions]}, size=20)
