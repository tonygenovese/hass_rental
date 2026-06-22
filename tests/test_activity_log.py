"""Tests for the activity log module (persistence, pagination, filtering)."""
from __future__ import annotations

import json
import os

import pytest

import app.activity_log as log_module
from app.activity_log import add, get_page, init, recent


@pytest.fixture(autouse=True)
def isolated_log(tmp_path, monkeypatch):
    """Redirect log storage to a temp dir and reset in-memory state before each test."""
    log_file = str(tmp_path / "activity_log.json")
    monkeypatch.setattr(log_module, "LOG_PATH", log_file)
    monkeypatch.setattr(log_module, "_entries", [])
    yield log_file


# ── init ──────────────────────────────────────────────────────────────────────

def test_init_with_no_file_gives_empty_list(isolated_log):
    init()
    assert log_module._entries == []


def test_init_loads_existing_file(isolated_log, tmp_path):
    existing = [{"id": "abc", "timestamp": "2026-01-01T00:00:00+00:00",
                  "type": "info", "message": "hello", "guest": None}]
    with open(isolated_log, "w") as f:
        json.dump(existing, f)
    init()
    assert len(log_module._entries) == 1
    assert log_module._entries[0]["message"] == "hello"


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_creates_entry_with_required_fields():
    entry = add("checkin", "Guest arrived", guest="John")
    assert entry["type"] == "checkin"
    assert entry["message"] == "Guest arrived"
    assert entry["guest"] == "John"
    assert "id" in entry
    assert "timestamp" in entry


def test_add_entry_appears_in_entries_list():
    add("info", "Test message")
    assert len(log_module._entries) == 1
    assert log_module._entries[0]["message"] == "Test message"


def test_add_persists_to_file(isolated_log):
    add("checkout", "Guest left")
    with open(isolated_log) as f:
        saved = json.load(f)
    assert len(saved) == 1
    assert saved[0]["type"] == "checkout"


def test_add_without_guest_stores_none():
    entry = add("info", "System note")
    assert entry["guest"] is None


def test_add_timestamps_are_iso_format():
    entry = add("info", "ts test")
    # Should parse without error
    from datetime import datetime
    dt = datetime.fromisoformat(entry["timestamp"])
    assert dt.tzinfo is not None  # must be timezone-aware


# ── max entries trimming ──────────────────────────────────────────────────────

def test_exceeding_max_entries_trims_oldest(monkeypatch):
    monkeypatch.setattr(log_module, "MAX_ENTRIES", 5)
    for i in range(7):
        add("info", f"entry {i}")
    assert len(log_module._entries) == 5
    # Oldest should be gone; newest should remain
    messages = [e["message"] for e in log_module._entries]
    assert "entry 0" not in messages
    assert "entry 6" in messages


# ── recent ────────────────────────────────────────────────────────────────────

def test_recent_returns_newest_first():
    add("info", "first")
    add("info", "second")
    add("info", "third")
    r = recent(2)
    assert r[0]["message"] == "third"
    assert r[1]["message"] == "second"


def test_recent_respects_n_limit():
    for i in range(10):
        add("info", f"msg {i}")
    assert len(recent(3)) == 3


def test_recent_returns_all_if_fewer_than_n():
    add("info", "only one")
    assert len(recent(10)) == 1


# ── get_page (pagination) ─────────────────────────────────────────────────────

def test_get_page_returns_newest_first():
    add("info", "first")
    add("info", "second")
    add("info", "third")
    result = get_page(page=1, limit=10)
    messages = [e["message"] for e in result["entries"]]
    assert messages[0] == "third"
    assert messages[-1] == "first"


def test_get_page_pagination():
    for i in range(10):
        add("info", f"msg {i}")
    page1 = get_page(page=1, limit=4)
    page2 = get_page(page=2, limit=4)
    assert len(page1["entries"]) == 4
    assert len(page2["entries"]) == 4
    assert page1["entries"][0]["message"] != page2["entries"][0]["message"]


def test_get_page_total_reflects_all_entries():
    for i in range(7):
        add("info", f"msg {i}")
    result = get_page(page=1, limit=3)
    assert result["total"] == 7
    assert len(result["entries"]) == 3


def test_get_page_last_page_has_remainder():
    for i in range(7):
        add("info", f"msg {i}")
    result = get_page(page=3, limit=3)
    assert len(result["entries"]) == 1


# ── get_page (filtering) ──────────────────────────────────────────────────────

def test_filter_by_type():
    add("checkin", "Guest arrived", guest="Alice")
    add("info", "System note")
    add("checkout", "Guest left", guest="Alice")
    add("checkin", "Second guest arrived", guest="Bob")

    result = get_page(page=1, limit=50, log_type="checkin")
    assert result["total"] == 2
    assert all(e["type"] == "checkin" for e in result["entries"])


def test_filter_none_returns_all():
    add("checkin", "In")
    add("checkout", "Out")
    add("error", "Oops")
    result = get_page(page=1, limit=50, log_type=None)
    assert result["total"] == 3


def test_filter_with_no_matches_returns_empty():
    add("info", "something")
    result = get_page(page=1, limit=50, log_type="error")
    assert result["total"] == 0
    assert result["entries"] == []
