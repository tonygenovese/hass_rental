"""Tests for settings load/save/mask logic."""
from __future__ import annotations

import json

import app.settings as settings_module
from app.settings import DEFAULTS, load, masked, save


# ── load ──────────────────────────────────────────────────────────────────────

def test_load_returns_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    result = load()
    assert result == DEFAULTS


def test_load_merges_stored_values_over_defaults(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)
    with open(path, "w") as f:
        json.dump({"ical_url": "http://example.com/cal.ics", "guest_temp": 74}, f)

    result = load()
    assert result["ical_url"] == "http://example.com/cal.ics"
    assert result["guest_temp"] == 74
    # Defaults are preserved for keys not in stored file
    assert result["away_temp"] == DEFAULTS["away_temp"]
    assert result["poll_interval_minutes"] == DEFAULTS["poll_interval_minutes"]


def test_load_all_defaults_present(tmp_path, monkeypatch):
    """Every key in DEFAULTS must be present in the loaded result."""
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    result = load()
    for key in DEFAULTS:
        assert key in result, f"Missing default key: {key}"


def test_load_with_partial_stored_file(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)
    with open(path, "w") as f:
        json.dump({"lock_entity_id": "lock.front_door"}, f)

    result = load()
    assert result["lock_entity_id"] == "lock.front_door"
    assert result["cleaner_code"] == ""  # default preserved


# ── save ──────────────────────────────────────────────────────────────────────

def test_save_writes_json_file(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)
    data = {**DEFAULTS, "ical_url": "http://test.example.com/cal.ics"}
    save(data)

    with open(path) as f:
        written = json.load(f)
    assert written["ical_url"] == "http://test.example.com/cal.ics"


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)
    data = {**DEFAULTS, "guest_code_slot": 5, "cleaner_code": "999888"}
    save(data)
    result = load()
    assert result["guest_code_slot"] == 5
    assert result["cleaner_code"] == "999888"


def test_save_creates_directory_if_missing(tmp_path, monkeypatch):
    nested = str(tmp_path / "deep" / "path" / "settings.json")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", nested)
    save(DEFAULTS)
    import os
    assert os.path.exists(nested)


# ── masked ────────────────────────────────────────────────────────────────────

def test_masked_hides_cleaner_code():
    data = {**DEFAULTS, "cleaner_code": "123456"}
    result = masked(data)
    assert result["cleaner_code"] == "••••"


def test_masked_does_not_mutate_original():
    data = {**DEFAULTS, "cleaner_code": "123456"}
    _ = masked(data)
    assert data["cleaner_code"] == "123456"


def test_masked_empty_cleaner_code_unchanged():
    """An empty cleaner code (not yet set) should not be masked."""
    data = {**DEFAULTS, "cleaner_code": ""}
    result = masked(data)
    assert result["cleaner_code"] == ""


def test_masked_preserves_all_other_fields():
    data = {**DEFAULTS, "cleaner_code": "555", "ical_url": "http://example.com", "guest_temp": 73}
    result = masked(data)
    assert result["ical_url"] == "http://example.com"
    assert result["guest_temp"] == 73
    assert result["lock_entity_id"] == DEFAULTS["lock_entity_id"]
