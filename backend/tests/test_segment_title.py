"""
Tests for the per-segment public `title` field (issue #182), and for the
removal of its companion `note` (issue #406).

Every session segment has one optional, public free-text field, `title`
(max 100 chars). It is distinct from the private, admin-only session-level
`coach_notes`: `title` IS public, rendering in the iCal event DESCRIPTION and
in the in-app session detail breakdown.

`note` (max 280 chars) sat beside it until #406 removed it. Per-segment prose
only reads correctly next to its segment; the session-level `info` field is
where prose about a session belongs. The tests at the bottom of this file pin
that removal: the schema no longer has the field, and the iCal renderer filters
by allow-list so a row written before the column was dropped cannot leak into
a feed.

The iCal per-segment line is a `" - "`-joined list of
`[time-range, types, title?]`, skipping title when absent. The time-range and
the comma-joined type list are always present.

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
    """No title: line is 'time-range - types'."""
    ical = build_ical([_session_with_segment()])
    line = _description_line(ical)
    assert "20:00-20:30 - Basics" in line
    # No dangling separators.
    assert "20:00-20:30 - Basics -" not in line


def test_segment_line_with_title() -> None:
    ical = build_ical([_session_with_segment(title="Footwork and out of bogu drills")])
    line = _description_line(ical)
    assert "20:00-20:30 - Basics - Footwork and out of bogu drills" in line


def test_segment_line_multi_type_with_title() -> None:
    """Multiple types stay comma-joined within their slot; title follows."""
    ical = build_ical(
        [
            _session_with_segment(
                type_names=["Jigeki", "Kata Practice"],
                title="Pairs",
            )
        ]
    )
    line = _description_line(ical)
    # RFC 5545 escapes the comma in the joined type list to "\,".
    assert "20:00-20:30 - Jigeki\\, Kata Practice - Pairs" in line


def test_segment_title_is_public() -> None:
    """Unlike coach_notes, title must reach the public iCal output."""
    ical = build_ical(
        [
            _session_with_segment(
                title="Public Title",
                coach_notes="SECRET private note",
            )
        ]
    )
    assert "Public Title" in ical
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


def test_title_defaults_to_none() -> None:
    seg = SegmentCreate(**_segment_kwargs())
    assert seg.title is None


def test_title_max_length_100_accepts_boundary() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="x" * 100))
    assert seg.title == "x" * 100


def test_title_over_100_rejected() -> None:
    with pytest.raises(ValidationError):
        SegmentCreate(**_segment_kwargs(title="x" * 101))


def test_whitespace_only_title_normalized_to_none() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="   "))
    assert seg.title is None


def test_title_is_trimmed() -> None:
    seg = SegmentCreate(**_segment_kwargs(title="  Warmup  "))
    assert seg.title == "Warmup"


# ---------------------------------------------------------------------------
# Generation — template segment title copied into generated instances
# ---------------------------------------------------------------------------


def test_generate_instances_copies_title() -> None:
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
                "type_ids": ["t1"],
            }
        ],
    }

    instances = generate_instances(template, date(2025, 3, 18))
    assert len(instances) >= 2
    for inst in instances:
        seg = inst["segments"][0]
        assert seg["title"] == "Warm up"

    # Overridable per instance: mutating one instance never reaches the
    # template or a sibling.
    instances[0]["segments"][0]["title"] = "Different"
    assert template["segments"][0]["title"] == "Warm up"
    assert instances[1]["segments"][0]["title"] == "Warm up"


# ── #406: the per-segment note is removed ────────────────────────────────────


def test_segment_create_drops_note() -> None:
    """A payload that still carries `note` is accepted and the value discarded
    (models keep Pydantic's default extra="ignore"), but the field is gone."""
    seg = SegmentCreate(**_segment_kwargs(note="no longer a field"))
    assert not hasattr(seg, "note")


def test_segment_line_omits_a_lingering_note() -> None:
    """Rows written before the column was dropped must not reach the feed.

    The renderer takes dicts straight from the repository, so it filters by
    allow-list rather than trusting the caller's keys.
    """
    ical = build_ical([_session_with_segment(title="Kihon", note="stale text")])
    assert "Kihon" in ical
    assert "stale text" not in ical
