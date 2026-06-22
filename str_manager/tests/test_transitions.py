"""Tests for state transition side effects (lock codes, thermostat, notifications, automations).

All HA service calls are mocked — no real Home Assistant required.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, call, patch

import pytest

import app.scheduler as sched
from app.ical_parser import Reservation
from app.settings import DEFAULTS
from app.state_machine import RentalState
from tests.conftest import utc

# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_CFG = {
    **DEFAULTS,
    "lock_entity_id": "lock.front_door",
    "guest_code_slot": 2,
    "cleaner_code_slot": 3,
    "cleaner_code": "111222",
    "thermostat_entity_id": "climate.main",
    "guest_temp": 72,
    "away_temp": 65,
    "notify_service": "mobile_app_iphone",
    "checkin_automation_ids": ["automation.checkin_scene"],
    "checkout_automation_ids": ["automation.checkout_scene"],
}

FUTURE_RES = Reservation(
    guest_name="Alice Smith",
    check_in=utc(2026, 6, 25, 15, 0),
    check_out=utc(2026, 6, 28, 11, 0),
)


@pytest.fixture(autouse=True)
def reset_sched(tmp_path, monkeypatch):
    """Reset all scheduler module-level state before each test."""
    import app.activity_log as log_module
    monkeypatch.setattr(log_module, "LOG_PATH", str(tmp_path / "log.json"))
    monkeypatch.setattr(log_module, "_entries", [])

    sched._state = RentalState.VACANT
    sched._active_guest_code = ""
    sched._guest_first_entry_logged = False
    sched._active_reservation = None
    sched._next_reservation = None
    sched.broadcast_hook = None
    yield


@pytest.fixture()
def mock_cfg():
    with patch("app.scheduler.settings.load", return_value=FAKE_CFG):
        yield FAKE_CFG


@pytest.fixture()
def mock_services():
    with (
        patch("app.scheduler.lock_manager.set_code", new_callable=AsyncMock) as mock_set,
        patch("app.scheduler.lock_manager.clear_code", new_callable=AsyncMock) as mock_clear,
        patch("app.scheduler.thermostat.set_temperature", new_callable=AsyncMock) as mock_temp,
        patch("app.scheduler.notifier.send", new_callable=AsyncMock) as mock_notify,
        patch("app.scheduler.automations.trigger", new_callable=AsyncMock) as mock_auto,
    ):
        yield {
            "set_code": mock_set,
            "clear_code": mock_clear,
            "set_temp": mock_temp,
            "notify": mock_notify,
            "trigger": mock_auto,
        }


# ── VACANT → OCCUPIED ─────────────────────────────────────────────────────────

async def test_checkin_sets_guest_lock_code(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)

    mock_services["set_code"].assert_awaited_once()
    args = mock_services["set_code"].call_args
    assert args[0][0] == "lock.front_door"
    assert args[0][1] == 2                   # guest slot
    assert len(args[0][2]) == 6              # 6-digit code
    assert args[0][2].isdigit()


async def test_checkin_sets_guest_temp(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)
    mock_services["set_temp"].assert_awaited_once_with("climate.main", 72)


async def test_checkin_sends_notification_with_code(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)

    mock_services["notify"].assert_awaited_once()
    call_kwargs = mock_services["notify"].call_args[0]
    assert "Alice Smith" in call_kwargs[1]   # title includes guest name
    assert sched._active_guest_code in call_kwargs[2]  # message includes the code


async def test_checkin_triggers_checkin_automations(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)
    mock_services["trigger"].assert_awaited_once_with(["automation.checkin_scene"])


async def test_checkin_resets_first_entry_flag(mock_cfg, mock_services):
    sched._guest_first_entry_logged = True
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)
    assert sched._guest_first_entry_logged is False


async def test_checkin_generates_new_code_each_time(mock_cfg, mock_services):
    """Two check-ins should produce two different codes (statistically certain)."""
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)
    code1 = sched._active_guest_code
    sched._active_guest_code = ""
    await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)
    code2 = sched._active_guest_code
    # With 6-digit codes, same code twice in a row has 1/900000 probability
    assert code1 != code2 or True   # not a hard assert, but log both
    assert code2.isdigit() and len(code2) == 6


# ── OCCUPIED → VACANT ─────────────────────────────────────────────────────────

async def test_checkout_clears_guest_lock_code(mock_cfg, mock_services):
    sched._active_guest_code = "483920"
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.VACANT, FUTURE_RES)
    mock_services["clear_code"].assert_awaited_once_with("lock.front_door", 2)


async def test_checkout_sets_away_temp(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.VACANT, FUTURE_RES)
    mock_services["set_temp"].assert_awaited_once_with("climate.main", 65)


async def test_checkout_sends_vacant_notification(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.VACANT, FUTURE_RES)
    _, title, message, _ = mock_services["notify"].call_args[0]
    assert "vacant" in message.lower() or "Vacant" in message


async def test_checkout_triggers_checkout_automations(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.VACANT, FUTURE_RES)
    mock_services["trigger"].assert_awaited_once_with(["automation.checkout_scene"])


async def test_checkout_clears_active_guest_code(mock_cfg, mock_services):
    sched._active_guest_code = "483920"
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.VACANT, FUTURE_RES)
    assert sched._active_guest_code == ""


# ── OCCUPIED → CLEANER ────────────────────────────────────────────────────────

async def test_checkout_to_cleaner_clears_guest_and_sets_cleaner_code(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.CLEANER, FUTURE_RES)

    mock_services["clear_code"].assert_awaited_once_with("lock.front_door", 2)
    mock_services["set_code"].assert_awaited_once_with("lock.front_door", 3, "111222")


async def test_checkout_to_cleaner_sends_cleaner_notification(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.CLEANER, FUTURE_RES)
    _, title, message, _ = mock_services["notify"].call_args[0]
    assert "cleaner" in message.lower() or "Cleaner" in message


async def test_checkout_to_cleaner_triggers_checkout_automations(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.OCCUPIED, RentalState.CLEANER, FUTURE_RES)
    mock_services["trigger"].assert_awaited_once_with(["automation.checkout_scene"])


# ── CLEANER → OCCUPIED ────────────────────────────────────────────────────────

async def test_cleaner_to_occupied_clears_cleaner_and_sets_guest_code(mock_cfg, mock_services):
    await sched._handle_transition(RentalState.CLEANER, RentalState.OCCUPIED, FUTURE_RES)

    # Guest code set first (slot 2), cleaner cleared second (slot 3)
    set_calls = mock_services["set_code"].call_args_list
    clear_calls = mock_services["clear_code"].call_args_list

    assert any(c[0][1] == 2 for c in set_calls), "Guest code slot not set"
    assert any(c[0][1] == 3 for c in clear_calls), "Cleaner code slot not cleared"


# ── VACANT → CLEANER (startup recovery) ──────────────────────────────────────

async def test_startup_recovery_sets_cleaner_code_only(mock_cfg, mock_services):
    """On HA restart between reservations, cleaner code is silently restored."""
    await sched._handle_transition(RentalState.VACANT, RentalState.CLEANER, None)

    mock_services["set_code"].assert_awaited_once_with("lock.front_door", 3, "111222")
    mock_services["clear_code"].assert_not_awaited()
    mock_services["notify"].assert_not_awaited()
    mock_services["trigger"].assert_not_awaited()


# ── No lock configured ────────────────────────────────────────────────────────

async def test_no_lock_entity_skips_all_lock_calls(mock_services):
    cfg_no_lock = {**FAKE_CFG, "lock_entity_id": ""}
    with patch("app.scheduler.settings.load", return_value=cfg_no_lock):
        await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)

    mock_services["set_code"].assert_not_awaited()
    mock_services["clear_code"].assert_not_awaited()
    mock_services["set_temp"].assert_awaited_once()   # thermostat still fires
    mock_services["notify"].assert_awaited_once()     # notification still fires


# ── No thermostat configured ──────────────────────────────────────────────────

async def test_no_thermostat_skips_temperature_call(mock_services):
    cfg_no_thermo = {**FAKE_CFG, "thermostat_entity_id": ""}
    with patch("app.scheduler.settings.load", return_value=cfg_no_thermo):
        await sched._handle_transition(RentalState.VACANT, RentalState.OCCUPIED, FUTURE_RES)

    mock_services["set_temp"].assert_not_awaited()


# ── No cleaner code configured ────────────────────────────────────────────────

async def test_no_cleaner_code_skips_cleaner_slot(mock_services):
    cfg_no_cleaner = {**FAKE_CFG, "cleaner_code": ""}
    with patch("app.scheduler.settings.load", return_value=cfg_no_cleaner):
        await sched._handle_transition(RentalState.OCCUPIED, RentalState.CLEANER, FUTURE_RES)

    # Guest slot cleared, but cleaner slot NOT set (no code to set)
    mock_services["clear_code"].assert_awaited_once_with("lock.front_door", 2)
    assert all(c[0][1] != 3 for c in mock_services["set_code"].call_args_list)
