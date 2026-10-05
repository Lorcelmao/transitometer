"""Axis A passage messages: stable keys and canonical values."""

from __future__ import annotations

import json

from transitometer.axis_a.produce import END, FIELDS, end_marker, key_of, value_of

ROW = {
    "grp": "bus",
    "service_date": "20260922",
    "route_id": "B6",
    "stop_id": "301234",
    "service_hour": 7,
    "trip_key": "EN_B6-123",
    "trip_id": "EN_B6-123",
    "unit": "MTA NYCT_7012",
    "source": "scheduled",
    "observed_arrival": 1790154126,
    "delay_s": 73,
    "ref_headway_s": 480.0,
}


def test_key_groups_one_stop_of_one_route_and_day() -> None:
    assert key_of(ROW) == b"bus|20260922|B6|301234"


def test_value_is_canonical_json_in_field_order() -> None:
    raw = value_of(ROW)
    assert raw.startswith(b'{"grp":"bus","service_date":"20260922"')
    assert b" " not in raw.replace(b"MTA NYCT", b"")  # no separator spaces
    assert list(json.loads(raw)) == list(FIELDS)
    assert value_of(dict(reversed(list(ROW.items())))) == raw  # input order is irrelevant


def test_null_delay_and_reference_stay_null() -> None:
    body = json.loads(
        value_of({**ROW, "source": "unscheduled", "delay_s": None, "ref_headway_s": None})
    )
    assert body["delay_s"] is None and body["ref_headway_s"] is None


def test_end_marker_is_one_day_after_the_last_passage_and_recognisable() -> None:
    marker = end_marker(1790154126)
    assert marker["grp"] == END and marker["observed_arrival"] == 1790154126 + 86_400
    assert key_of(marker) == f"{END}|{END}|{END}|{END}".encode()
    assert json.loads(value_of(marker))["delay_s"] is None
