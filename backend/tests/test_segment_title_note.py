"""
Tests for issue #182 — per-segment public `title` and `note` fields.

Every session segment gains two optional, public free-text fields:
  - `title` (max 100 chars)
  - `note`  (max 280 chars)

They are distinct from the private, admin-only `coach_notes`. Title and note
ARE public: they render in the iCal event DESCRIPTION and in the in-app
session detail breakdown.

The iCal per-segment line becomes a `" - "`-joined list of
`[time-range, types, title?, note?]`, skipping title/note when absent. The
time-range and the comma-joined type list are always present.

These tests exercise the pure `build_ical` renderer, the `SegmentCreate`
schema validation/normalization, and the pure `generate_instances` copy —
no DB, no I/O.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.sessions.ical import build_ical
from app.sessions.models import SegmentCreate
from app.sessions.service import generate_instances


def _session_with_segment(**seg_overrides):
    segment = {
        "start_time": "20:00",
        "duration_minutes": 30,
        "type_names": ["Basics"],
    }
    segment.update(seg_overrides)
    return {
        "id": "uid-1",
        "title": "Evening Training",
        "date": "2099-11-07",
        "info": None,
        "cancelled": False,
        "segments": [segment],
    }


def _description_line(ical: str) -> str:
    return next(line for line in ical.split("\r\n") if line.startswith("DESCRIPTION:"))


# ---------------------------------------------------------------------------
# iCal segment-line renderer — the deep module (primary behavioural value)
# ---------------------------------------------------------------------------


def test_segment_line_type_only() -> None:
    """No title or note: line is 'time-range - types'."""
    ical = build_ical([_session_with_segment()])
    line = _description_line(ical)
    assert "20:00-20:30 - Basics" in line
    # No dangling separators.
    assert "20:00-20:30 - Basics -" not in line


def test_segment_line_with_title() -> None:
    ical = build_ical([_session_with_segment(title="Footwork and out of bogu drills")])
    line = _description_line(ical)
    assert "20:00-20:30 - Basics - Footwork and out of bogu drills" in line


def test_segment_line_with_note_only() -> None:
    """Note but no title: note follows the types directly."""
    ical = build_ical([_session_with_segment(note="In bogu practice basics")])
    line = _description_line(ical)
    assert "20:00-20:30 - Basics - In bogu practice basics" in line


def test_segment_line_with_title_and_note() -> None:
    ical = build_ical(
        [
            _session_with_segment(
                start_time="20:30",
                duration_minutes=60,
                type_names=["Kihon"],
                title="In bogu practice basics",
                note="Today focus nuki-do.",
            )
        ]
    )
    line = _description_line(ical)
    assert (
        "20:30-21:30 - Kihon - In bogu practice basics - Today focus nuki-do." in line
    )


def test_segment_line_multi_type_with_title_and_note() -> None:
    """Multiple types stay comma-joined within their slot; title/note follow."""
    ical = build_ical(
        [
            _session_with_segment(
                type_names=["Jigeki", "Kata Practice"],
                title="Pairs",
                note="rotate every 5 min",
            )
        ]
    )
    line = _description_line(ical)
    # RFC 5545 escapes the comma in the joined type list to "\,".
    assert "20:00-20:30 - Jigeki\\, Kata Practice - Pairs - rotate every 5 min" in line


def test_segment_title_and_note_are_public() -> None:
    """Unlike coach_notes, title/note must reach the public iCal output."""
    ical = build_ical(
        [
            _session_with_segment(
                title="Public Title",
                note="Public Note",
                coach_notes="SECRET private note",
            )
        ]
    )
    assert "Public Title" in ical
    assert "Public Note" in ical
    assert "SECRET private note" not in ical


# ---------------------------------------------------------------------------
# Schema validation & normalization
# ---------------------------------------------------------------------------


def _segment_kwargs(**overrides):
    base = {
        "start_time": "19:00",
        "duration_minutes": 60,
        "type_ids": ["t1"],
    }
    base.update(overrides)
    return base


def test_title_and_note_default_to_none() -> None:
    seg = SegmentCreate(**_segment_kwargs())
    assert seg.title is None
    assert seg.note is None


def test_title_max_length_100_accepts_boundary() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="x" * 100))
    assert seg.title == "x" * 100


def test_title_over_100_rejected() -> None:
    with pytest.raises(ValidationError):
        SegmentCreate(**_segment_kwargs(title="x" * 101))


def test_note_max_length_280_accepts_boundary() -> None:
    seg = SegmentCreate(**_segment_kwargs(note="y" * 280))
    assert seg.note == "y" * 280


def test_note_over_280_rejected() -> None:
    with pytest.raises(ValidationError):
        SegmentCreate(**_segment_kwargs(note="y" * 281))


def test_whitespace_only_title_normalized_to_none() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="   "))
    assert seg.title is None


def test_whitespace_only_note_normalized_to_none() -> None:
    seg = SegmentCreate(**_segment_kwargs(note="\t \n"))
    assert seg.note is None


def test_title_and_note_are_trimmed() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="  Warmup  ", note="  focus  "))
    assert seg.title == "Warmup"
    assert seg.note == "focus"


# ---------------------------------------------------------------------------
# Generation — template segment title/note copied into generated instances
# ---------------------------------------------------------------------------


def test_generate_instances_copies_title_and_note() -> None:
    template = {
        "id": str(uuid.uuid4()),
        "title": "Tuesday Keiko",
        "start_date": "2025-03-04",  # Tuesday
        "recurrence_days": [1],
        "interval_weeks": 1,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 60,
                "title": "Warm up",
                "note": "gentle suburi",
                "type_ids": ["t1"],
            }
        ],
    }

    instances = generate_instances(template, date(2025, 3, 18))
    assert len(instances) >= 2
    for inst in instances:
        seg = inst["segments"][0]
        assert seg["title"] == "Warm up"
        assert seg["note"] == "gentle suburi"

    # Overridable per instance: mutating one instance never reaches the
    # template or a sibling.
    instances[0]["segments"][0]["title"] = "Different"
    assert template["segments"][0]["title"] == "Warm up"
    assert instances[1]["segments"][0]["title"] == "Warm up"
