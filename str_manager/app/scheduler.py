import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import activity_log, automations, ha_client, lock_manager, notifier, settings
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
    return {
        "state": _state,
        "current_guest": active.guest_name if active else None,
        "check_in": active.check_in.isoformat() if active else None,
        "check_out": active.check_out.isoformat() if active else None,
        "guest_code": _active_guest_code if active else None,
        "phone_last4": active.phone_last4 if active else None,
        "next_guest": nxt.guest_name if nxt else None,
        "next_check_in": nxt.check_in.isoformat() if nxt else None,
        "last_sync": _last_sync.isoformat() if _last_sync else None,
    }


def get_reservations() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "guest_name": r.guest_name,
            "check_in": r.check_in.isoformat(),
            "check_out": r.check_out.isoformat(),
            "duration_nights": max(1, (r.check_out.date() - r.check_in.date()).days),
            "is_active": r.is_active(now),
            "phone_last4": r.phone_last4,
        }
        for r in _reservations
        if r.check_out > now
    ]


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

    if new == RentalState.OCCUPIED:
        _guest_first_entry_logged = False
        _cleaner_present = False
        _active_guest_code = str(random.randint(100000, 999999))

        for lid in lock_ids:
            await lock_manager.set_code(lid, guest_slot, _active_guest_code)
        if lock_ids:
            activity_log.add("code_set", f"Guest code set in slot {guest_slot}: {_active_guest_code}", guest_name)

        if old == RentalState.CLEANER:
            for lid in lock_ids:
                await lock_manager.clear_code(lid, cleaner_slot)
            if lock_ids:
                activity_log.add("code_cleared", f"Cleaner code cleared from slot {cleaner_slot}")

        msg = f"Guest checked in. Access code: {_active_guest_code}"
        await notifier.send(notify_svc, f"Check-in: {guest_name}", msg, "str_mgr_checkin")
        activity_log.add("checkin", f"{guest_name} checked in. Code: {_active_guest_code}", guest_name)
        await automations.trigger(cfg.get("checkin_automation_ids", []))

    elif new == RentalState.CLEANER and old != RentalState.OCCUPIED:
        for lid in lock_ids:
            if cleaner_code:
                await lock_manager.set_code(lid, cleaner_slot, cleaner_code)
        if lock_ids and cleaner_code:
            activity_log.add("code_set", f"Cleaner code restored in slot {cleaner_slot} (startup recovery)")

    elif old == RentalState.OCCUPIED and new in (RentalState.VACANT, RentalState.CLEANER):
        _cleaner_present = False
        for lid in lock_ids:
            await lock_manager.clear_code(lid, guest_slot)
        if lock_ids:
            activity_log.add("code_cleared", f"Guest code cleared from slot {guest_slot}", guest_name)

        if new == RentalState.CLEANER:
            for lid in lock_ids:
                if cleaner_code:
                    await lock_manager.set_code(lid, cleaner_slot, cleaner_code)
            if lock_ids and cleaner_code:
                activity_log.add("code_set", f"Cleaner code set in slot {cleaner_slot}")
            await notifier.send(notify_svc, "Guest Checked Out", "Cleaner mode active.", "str_mgr_checkout")
            activity_log.add("checkout", f"{guest_name} checked out. Cleaner mode active.", guest_name)
        else:
            await notifier.send(notify_svc, "Guest Checked Out", "Property is vacant.", "str_mgr_checkout")
            activity_log.add("checkout", f"{guest_name} checked out. Property vacant.", guest_name)

        _active_guest_code = ""
        await automations.trigger(cfg.get("checkout_automation_ids", []))

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
        msg = "Cleaner locked up and left the property."
        await notifier.send(notify_svc, "Cleaner Left", msg, "str_mgr_cleaner_exit")
        activity_log.add("cleaner_entry", msg)
        pre_autos = cfg.get("pre_checkin_automation_ids", [])
        if pre_autos:
            await automations.trigger(pre_autos)
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
                steps.append({"icon": "🔔", "text": "Send check-in notification"})
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
            lbl = " · cleaner mode" if is_cleaner_after else ""
            steps.append({"icon": "🔔", "text": f"Send check-out notification{lbl}"})
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
