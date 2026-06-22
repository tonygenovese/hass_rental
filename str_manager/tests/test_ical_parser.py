"""Tests for iCal fetch and parsing logic."""
from __future__ import annotations

from datetime import time, timezone
from unittest.mock import patch

import pytest

from app.ical_parser import fetch_reservations
from tests.conftest import make_ical, mock_aiohttp_get, utc

URL = "http://example.com/cal.ics"


# ── Date-only events ──────────────────────────────────────────────────────────

async def test_date_only_events_use_default_times():
    """DATE-only iCal events should be combined with the configured default times."""
    ical = make_ical(
        {"summary": "John Smith", "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL, default_checkin="15:00", default_checkout="11:00")

    assert len(results) == 1
    r = results[0]
    assert r.guest_name == "John Smith"
    assert r.check_in.time() == time(15, 0)
    assert r.check_out.time() == time(11, 0)
    assert r.check_in.date().isoformat() == "2026-06-25"
    assert r.check_out.date().isoformat() == "2026-06-28"


async def test_date_only_respects_custom_default_times():
    ical = make_ical(
        {"summary": "Guest", "dtstart": "20260701", "dtend": "20260704"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL, default_checkin="16:00", default_checkout="10:00")

    r = results[0]
    assert r.check_in.time() == time(16, 0)
    assert r.check_out.time() == time(10, 0)


# ── Datetime events ───────────────────────────────────────────────────────────

async def test_datetime_events_preserve_exact_time():
    """Full datetime events should keep their exact time, ignoring the defaults."""
    ical = make_ical(
        {"summary": "Alice", "dtstart": "20260625T160000Z", "dtend": "20260628T100000Z"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL, default_checkin="15:00", default_checkout="11:00")

    r = results[0]
    assert r.check_in == utc(2026, 6, 25, 16, 0)
    assert r.check_out == utc(2026, 6, 28, 10, 0)


# ── Blocked / unavailable filtering ──────────────────────────────────────────

@pytest.mark.parametrize("summary", [
    "BLOCKED",
    "blocked",
    "Not available",
    "NOT AVAILABLE",
    "Airbnb (Not Available)",
    "AIRBNB (NOT AVAILABLE)",
])
async def test_blocked_events_are_filtered(summary: str):
    ical = make_ical(
        {"summary": summary, "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert results == [], f"Expected '{summary}' to be filtered out"


async def test_non_blocked_events_are_kept():
    ical = make_ical(
        {"summary": "Bob Jones", "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert len(results) == 1
    assert results[0].guest_name == "Bob Jones"


# ── Guest name stripping ──────────────────────────────────────────────────────

async def test_airbnb_reserved_prefix_stripped():
    ical = make_ical(
        {"summary": "Reserved - Jane Doe", "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert results[0].guest_name == "Jane Doe"


async def test_plain_summary_unchanged():
    ical = make_ical(
        {"summary": "Carlos Rivera", "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert results[0].guest_name == "Carlos Rivera"


# ── Sorting ───────────────────────────────────────────────────────────────────

async def test_results_sorted_by_check_in():
    ical = make_ical(
        {"summary": "Second Guest", "dtstart": "20260710", "dtend": "20260715"},
        {"summary": "First Guest",  "dtstart": "20260625", "dtend": "20260628"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert results[0].guest_name == "First Guest"
    assert results[1].guest_name == "Second Guest"


# ── Edge cases ────────────────────────────────────────────────────────────────

async def test_empty_calendar_returns_empty_list():
    ical = make_ical()  # no events
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert results == []


async def test_mixed_blocked_and_real_events():
    ical = make_ical(
        {"summary": "BLOCKED",    "dtstart": "20260620", "dtend": "20260622"},
        {"summary": "Real Guest", "dtstart": "20260625", "dtend": "20260628"},
        {"summary": "BLOCKED",    "dtstart": "20260701", "dtend": "20260703"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    assert len(results) == 1
    assert results[0].guest_name == "Real Guest"


async def test_http_error_raises():
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(b"", status=404)):
        with pytest.raises(Exception):
            await fetch_reservations(URL)


async def test_event_missing_dtstart_skipped():
    """Events without DTSTART/DTEND should be silently skipped."""
    raw = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        b"BEGIN:VEVENT\r\nSUMMARY:Incomplete\r\nEND:VEVENT\r\n"
        b"BEGIN:VEVENT\r\nSUMMARY:Complete\r\nDTSTART;VALUE=DATE:20260625\r\nDTEND;VALUE=DATE:20260628\r\nEND:VEVENT\r\n"
        b"END:VCALENDAR\r\n"
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(raw)):
        results = await fetch_reservations(URL)

    assert len(results) == 1
    assert results[0].guest_name == "Complete"


# ── Reservation model helpers ─────────────────────────────────────────────────

async def test_is_active_true_during_stay():
    ical = make_ical(
        {"summary": "Guest", "dtstart": "20260625T150000Z", "dtend": "20260628T110000Z"},
    )
    with patch("app.ical_parser.aiohttp.ClientSession", return_value=mock_aiohttp_get(ical)):
        results = await fetch_reservations(URL)

    r = results[0]
    assert r.is_active(utc(2026, 6, 26, 12, 0)) is True
    assert r.is_active(utc(2026, 6, 24, 23, 59)) is False
    assert r.is_active(utc(2026, 6, 28, 11, 0)) is False   # check_out is exclusive
