"""Shared fixtures and helpers for the test suite."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── iCal helpers ──────────────────────────────────────────────────────────────

def make_ical(*events: dict) -> bytes:
    """Build a minimal valid iCal byte string from a list of event dicts.

    Each event dict supports:
      summary  (str)
      dtstart  (str) — e.g. "20260625" (date) or "20260625T150000Z" (datetime)
      dtend    (str) — same formats
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Test//Test//EN",
    ]
    for ev in events:
        # Decide whether to emit VALUE=DATE or plain datetime format
        start = ev["dtstart"]
        end = ev["dtend"]
        start_prop = f"DTSTART;VALUE=DATE:{start}" if len(start) == 8 else f"DTSTART:{start}"
        end_prop = f"DTEND;VALUE=DATE:{end}" if len(end) == 8 else f"DTEND:{end}"
        lines += [
            "BEGIN:VEVENT",
            f"SUMMARY:{ev['summary']}",
            start_prop,
            end_prop,
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\n".join(lines).encode()


# ── aiohttp mock helper ───────────────────────────────────────────────────────

def mock_aiohttp_get(content: bytes, status: int = 200):
    """Return a patched aiohttp.ClientSession whose GET returns `content`."""
    import aiohttp

    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.read = AsyncMock(return_value=content)
    if status >= 400:
        mock_resp.raise_for_status.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=()
        )
    else:
        mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    return mock_session


# ── Time helpers ──────────────────────────────────────────────────────────────

def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
