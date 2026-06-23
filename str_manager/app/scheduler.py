import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import activity_log, automations, ha_client, lock_manager, notifier, options as addon_options, reservation_overrides, settings
from .ical_parser import Reservation, fetch_reservations
from .state_machine import RentalState, determine_state

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_state: RentalState = RentalState.VACANT
_reservations: list[Reservation] = []
_active_reservation: Reservation | None = None
_next_reservation: Reservation | None = None
_active_guest_code: str = ""
_guest_first_entry_logged: bool = False
_cleaner_present: bool = False
_last_sync: datetime | None = None
# WebSocket broadcast hook (set by main.py)
broadcast_hook: Any = None


def get_status() -> dict[str, Any]:
    active = _active_reservation
    nxt = _next_reservation

    check_in = check_out = None
    if active:
        ov = reservation_overrides.get(active.uid)
        check_in  = ov.get("check_in",  active.check_in.isoformat())
        check_out = ov.get("check_out", active.check_out.isoformat())

    return {
        "state": _state,
        "current_guest": active.guest_name if active else None,
        "uid": active.uid if active else None,
        "check_in":  check_in,
        "check_out": check_out,
        "guest_code": _active_guest_code if active else None,
        "phone_last4": active.phone_last4 if active else None,
        "next_guest": nxt.guest_name if nxt else None,
        "next_check_in": nxt.check_in.isoformat() if nxt else None,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
        "test_mode": addon_options.test_mode(),
    }


def get_reservations() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    result = []
    for r in _reservations:
        if r.check_out <= now:
            continue
        ov = reservation_overrides.get(r.uid)
        check_in  = ov.get("check_in",  r.check_in.isoformat())
        check_out = ov.get("check_out", r.check_out.isoformat())
        ci = datetime.fromisoformat(check_in)
        co = datetime.fromisoformat(check_out)
        result.append({
            "guest_name": r.guest_name,
            "check_in":   check_in,
            "check_out":  check_out,
            "duration_nights": max(1, (co.date() - ci.date()).days),
            "is_active": r.is_active(now),
            "phone_last4": r.phone_last4,
            "email": r.email,
            "adults": r.adults,
            "reservation_code": r.reservation_code,
            "uid": r.uid,
            "has_override": bool(ov),
        })
    return result


async def _broadcast(msg: dict[str, Any]) -> None:
    if broadcast_hook:
        await broadcast_hook(msg)


async def _handle_transition(old: RentalState, new: RentalState, reservation: Reservation | None) -> None:
    global _active_guest_code, _guest_first_entry_logged, _cleaner_present
    cfg = settings.load()

    lock_ids     = cfg.get("lock_entity_ids", [])
    guest_slot   = cfg.get("guest_code_slot", 2)
    cleaner_slot = cfg.get("cleaner_code_slot", 3)
    cleaner_code = cfg.get("cleaner_code", "")
    notify_svc   = cfg.get("notify_service", "")
    guest_name   = reservation.guest_name if reservation else "Guest"
    dry          = addon_options.test_mode()
    pfx          = "[TEST] " if dry else ""

    if new == RentalState.OCCUPIED:
        _guest_first_entry_logged = False
        _cleaner_present = False
        # Use phone last 4 as the access code; fall back to random 4-digit PIN
        if reservation and reservation.phone_last4:
            _active_guest_code = reservation.phone_last4
        else:
            _active_guest_code = str(random.randint(1000, 9999))

        if lock_ids:
            if not dry:
                for lid in lock_ids:
                    await lock_manager.set_code(lid, guest_slot, _active_guest_code)
            activity_log.add("code_set", f"{pfx}Guest code set in slot {guest_slot}: {_active_guest_code}", guest_name)

        if old == RentalState.CLEANER and lock_ids:
            if not dry:
                for lid in lock_ids:
                    await lock_manager.clear_code(lid, cleaner_slot)
            activity_log.add("code_cleared", f"{pfx}Cleaner code cleared from slot {cleaner_slot}")

        slot_info = f"slot {guest_slot}" if lock_ids else "no lock configured"
        msg = f"Check-in tasks done for {guest_name}. Code {_active_guest_code} set in {slot_info}."
        if not dry:
            await notifier.send(notify_svc, f"Ready for {guest_name}", msg, "str_mgr_checkin")
        activity_log.add("checkin", f"{pfx}Check-in tasks complete — {guest_name}. Code {_active_guest_code} set in {slot_info}.", guest_name)
        if not dry:
            await automations.trigger(cfg.get("checkin_automation_ids", []))
        elif cfg.get("checkin_automation_ids"):
            activity_log.add("info", f"{pfx}Would trigger {len(cfg['checkin_automation_ids'])} check-in automation(s)")

    elif new == RentalState.CLEANER and old != RentalState.OCCUPIED:
        if lock_ids and cleaner_code:
            if not dry:
                for lid in lock_ids:
                    await lock_manager.set_code(lid, cleaner_slot, cleaner_code)
            activity_log.add("code_set", f"{pfx}Cleaner code restored in slot {cleaner_slot} (startup recovery)")

    elif old == RentalState.OCCUPIED and new in (RentalState.VACANT, RentalState.CLEANER):
        _cleaner_present = False
        if lock_ids:
            if not dry:
                for lid in lock_ids:
                    await lock_manager.clear_code(lid, guest_slot)
            activity_log.add("code_cleared", f"{pfx}Guest code cleared from slot {guest_slot}", guest_name)

        if new == RentalState.CLEANER:
            if lock_ids and cleaner_code:
                if not dry:
                    for lid in lock_ids:
                        await lock_manager.set_code(lid, cleaner_slot, cleaner_code)
                activity_log.add("code_set", f"{pfx}Cleaner code set in slot {cleaner_slot}")
            co_msg = f"Check-out tasks done for {guest_name}. Guest code cleared. Cleaner mode active."
            if not dry:
                await notifier.send(notify_svc, "Check-out Complete", co_msg, "str_mgr_checkout")
            activity_log.add("checkout", f"{pfx}{co_msg}", guest_name)
        else:
            co_msg = f"Check-out tasks done for {guest_name}. Guest code cleared. Property is vacant."
            if not dry:
                await notifier.send(notify_svc, "Check-out Complete", co_msg, "str_mgr_checkout")
            activity_log.add("checkout", f"{pfx}{co_msg}", guest_name)

        _active_guest_code = ""
        if not dry:
            await automations.trigger(cfg.get("checkout_automation_ids", []))
        elif cfg.get("checkout_automation_ids"):
            activity_log.add("info", f"{pfx}Would trigger {len(cfg['checkout_automation_ids'])} check-out automation(s)")

    await _broadcast({"type": "status_update", "data": get_status()})
    await _broadcast({"type": "log_update", "data": activity_log.recent(5)})


async def poll() -> None:
    global _state, _reservations, _active_reservation, _next_reservation, _last_sync
    cfg = settings.load()
    ical_url = cfg.get("ical_url", "")

    if not ical_url:
        return

    try:
        _reservations = await fetch_reservations(
            ical_url,
            cfg.get("default_checkin_time", "15:00"),
            cfg.get("default_checkout_time", "11:00"),
            cfg.get("property_timezone", "America/New_York"),
        )
        _last_sync = datetime.now(timezone.utc)
    except Exception as exc:
        logger.error("iCal fetch failed: %s", exc)
        activity_log.add("error", f"Calendar sync failed: {exc}")
        await _broadcast({"type": "log_update", "data": activity_log.recent(5)})
        return

    now = datetime.now(timezone.utc)
    new_state = determine_state(_reservations, now)

    active = next((r for r in _reservations if r.is_active(now)), None)
    future = [r for r in _reservations if r.check_in > now]
    nxt = future[0] if future else None

    _active_reservation = active
    _next_reservation = nxt

    if new_state != _state:
        old_state = _state
        _state = new_state
        relevant = active or nxt
        asyncio.create_task(_handle_transition(old_state, new_state, relevant))
    else:
        await _broadcast({"type": "status_update", "data": get_status()})


async def handle_lock_event(event_data: dict[str, Any]) -> None:
    global _guest_first_entry_logged, _cleaner_present
    cfg = settings.load()
    lock_ids = cfg.get("lock_entity_ids", [])
    if not lock_ids:
        return

    # Match event node to one of our configured locks
    event_node = event_data.get("node_id")
    matched = False
    for lid in lock_ids:
        state = await ha_client.get_state(lid)
        if state and state.get("attributes", {}).get("node_id") == event_node:
            matched = True
            break
    if not matched:
        return

    notification_type = event_data.get("parameters", {}).get("notificationType")
    event_type        = event_data.get("parameters", {}).get("eventType")
    user_id           = event_data.get("parameters", {}).get("userId")

    if notification_type != 6:
        return

    guest_slot   = cfg.get("guest_code_slot", 2)
    cleaner_slot = cfg.get("cleaner_code_slot", 3)
    notify_svc   = cfg.get("notify_service", "")
    guest_name   = _active_reservation.guest_name if _active_reservation else "Guest"

    if event_type == 6:  # Keypad unlock
        if user_id == guest_slot and not _guest_first_entry_logged:
            _guest_first_entry_logged = True
            msg = f"{guest_name} has arrived and used their code for the first time."
            await notifier.send(notify_svc, "Guest Arrived!", msg, "str_mgr_first_entry")
            activity_log.add("first_entry", msg, guest_name)
            await _broadcast({"type": "log_update", "data": activity_log.recent(5)})
        elif user_id == cleaner_slot and not _cleaner_present:
            _cleaner_present = True
            msg = "Cleaner entered the property."
            await notifier.send(notify_svc, "Cleaner Arrived", msg, "str_mgr_cleaner_entry")
            activity_log.add("cleaner_entry", msg)
            await _broadcast({"type": "log_update", "data": activity_log.recent(5)})

    elif event_type in {1, 3, 5} and _cleaner_present:  # Any lock event while cleaner is inside
        _cleaner_present = False
        dry = addon_options.test_mode()
        pfx = "[TEST] " if dry else ""
        msg = "Cleaner locked up and left the property."
        if not dry:
            await notifier.send(notify_svc, "Cleaner Left", msg, "str_mgr_cleaner_exit")
        activity_log.add("cleaner_entry", f"{pfx}{msg}")
        pre_autos = cfg.get("pre_checkin_automation_ids", [])
        if pre_autos:
            if not dry:
                await automations.trigger(pre_autos)
            else:
                activity_log.add("info", f"{pfx}Would trigger {len(pre_autos)} pre-check-in automation(s)")
        await _broadcast({"type": "log_update", "data": activity_log.recent(5)})


def get_upcoming_actions(limit: int = 5, offset: int = 0) -> dict:
    cfg = settings.load()
    lock_ids       = cfg.get("lock_entity_ids", [])
    guest_slot     = cfg.get("guest_code_slot", 2)
    cleaner_slot   = cfg.get("cleaner_code_slot", 3)
    cleaner_code   = cfg.get("cleaner_code", "")
    notify_svc     = cfg.get("notify_service", "")
    checkin_autos  = cfg.get("checkin_automation_ids", [])
    checkout_autos = cfg.get("checkout_automation_ids", [])
    pre_checkin_autos = cfg.get("pre_checkin_automation_ids", [])
    has_locks = bool(lock_ids)
    lock_label = f"{len(lock_ids)} lock(s)" if len(lock_ids) > 1 else "lock"

    now = datetime.now(timezone.utc)
    relevant = [r for r in _reservations if r.check_out > now]
    actions: list[dict] = []

    for i, r in enumerate(relevant):
        next_r = relevant[i + 1] if i + 1 < len(relevant) else None
        prev_r = relevant[i - 1] if i > 0 else None
        is_cleaner_after = next_r is not None and (next_r.check_in - r.check_out) < timedelta(hours=24)
        is_after_cleaner = prev_r is not None and (r.check_in - prev_r.check_out) < timedelta(hours=24)

        if r.check_in > now:
            steps: list[dict] = []
            if has_locks:
                if is_after_cleaner:
                    steps.append({"icon": "🔓", "text": f"Clear cleaner code from slot {cleaner_slot}"})
                steps.append({"icon": "🔐", "text": f"Set guest code in slot {guest_slot} on {lock_label}"})
            if notify_svc:
                steps.append({"icon": "🔔", "text": "Notify: check-in tasks complete + code"})
            if checkin_autos:
                steps.append({"icon": "⚡", "text": f"Trigger {len(checkin_autos)} check-in automation(s)"})
            actions.append({
                "scheduled_at": r.check_in.isoformat(),
                "type": "checkin",
                "guest": r.guest_name,
                "steps": steps,
            })

        steps = []
        if has_locks:
            steps.append({"icon": "🔓", "text": f"Clear guest code from slot {guest_slot} on {lock_label}"})
            if is_cleaner_after and cleaner_code:
                steps.append({"icon": "🔐", "text": f"Set cleaner code in slot {cleaner_slot}"})
        if notify_svc:
            lbl = " (cleaner mode)" if is_cleaner_after else ""
            steps.append({"icon": "🔔", "text": f"Notify: check-out tasks complete{lbl}"})
        if checkout_autos:
            steps.append({"icon": "⚡", "text": f"Trigger {len(checkout_autos)} check-out automation(s)"})
        if is_cleaner_after and pre_checkin_autos:
            steps.append({"icon": "🧹", "text": f"Pre-check-in automation(s) fire when cleaner locks up ({len(pre_checkin_autos)} configured)"})
        actions.append({
            "scheduled_at": r.check_out.isoformat(),
            "type": "cleaner_start" if is_cleaner_after else "checkout",
            "guest": r.guest_name,
            "steps": steps,
        })

    total = len(actions)
    return {"actions": actions[offset: offset + limit], "total": total, "offset": offset, "limit": limit}


def get_managed_codes() -> dict:
    cfg = settings.load()
    return {
        "guest_slot":        cfg.get("guest_code_slot", 2),
        "cleaner_slot":      cfg.get("cleaner_code_slot", 3),
        "active_guest_code": _active_guest_code,
        "cleaner_code":      cfg.get("cleaner_code", ""),
        "state":             _state,
    }


def start(poll_interval_minutes: int = 30) -> None:
    _scheduler.add_job(poll, "interval", minutes=poll_interval_minutes, id="ical_poll", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()
    logger.info("Scheduler started with %d-minute poll interval", poll_interval_minutes)


def restart(poll_interval_minutes: int) -> None:
    _scheduler.reschedule_job("ical_poll", trigger="interval", minutes=poll_interval_minutes)
    logger.info("Scheduler rescheduled to %d-minute interval", poll_interval_minutes)


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
