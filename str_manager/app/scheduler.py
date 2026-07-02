import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import activity_log, automations, ha_client, lock_manager, notifier, options as addon_options, reservation_overrides, settings, manual_reservations as manual_res
from .ical_parser import Reservation, fetch_reservations
from .state_machine import RentalState, determine_state

logger = logging.getLogger(__name__)

_STATE_PATH = "/data/state.json"


def _save_state() -> None:
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump({
                "state": _state.value,
                "active_guest_code": _active_guest_code,
                "guest_first_entry_logged": _guest_first_entry_logged,
                "cleaner_present": _cleaner_present,
                "last_active_guest": _last_active_guest,
            }, f)
    except Exception as exc:
        logger.error("Failed to save runtime state: %s", exc)


def _load_state() -> None:
    global _state, _active_guest_code, _guest_first_entry_logged, _cleaner_present, _last_active_guest
    try:
        with open(_STATE_PATH) as f:
            data = json.load(f)
        _active_guest_code        = data.get("active_guest_code", "")
        _guest_first_entry_logged = data.get("guest_first_entry_logged", False)
        _cleaner_present          = data.get("cleaner_present", False)
        _last_active_guest        = data.get("last_active_guest", "")
        try:
            _state = RentalState(data.get("state", "vacant"))
        except ValueError:
            _state = RentalState.VACANT
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.error("Failed to load runtime state: %s", exc)


def _render(template: str, **kwargs: Any) -> str:
    for k, v in kwargs.items():
        template = template.replace(f"{{{k}}}", str(v))
    return template


_scheduler = AsyncIOScheduler()
_state: RentalState = RentalState.VACANT
_reservations: list[Reservation] = []
_active_reservation: Reservation | None = None
_next_reservation: Reservation | None = None
_active_guest_code: str = ""
_guest_first_entry_logged: bool = False
_cleaner_present: bool = False
_last_active_guest: str = ""
_last_sync: datetime | None = None
# WebSocket broadcast hook (set by main.py)
broadcast_hook: Any = None


def get_status() -> dict[str, Any]:
    active = _active_reservation
    nxt = _next_reservation

    # Overrides are already applied to reservation times at fetch (poll)
    check_in  = active.check_in.isoformat()  if active else None
    check_out = active.check_out.isoformat() if active else None

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
    overrides = reservation_overrides.load()
    result = []
    for r in _reservations:
        if r.check_out <= now:
            continue
        result.append({
            "guest_name": r.guest_name,
            "check_in":   r.check_in.isoformat(),
            "check_out":  r.check_out.isoformat(),
            "duration_nights": max(1, (r.check_out.date() - r.check_in.date()).days),
            "is_active": r.is_active(now),
            "phone_last4": r.phone_last4,
            "email": r.email,
            "adults": r.adults,
            "reservation_code": r.reservation_code,
            "uid": r.uid,
            "has_override": bool(overrides.get(r.uid)),
        })
    return result


async def _broadcast(msg: dict[str, Any]) -> None:
    if broadcast_hook:
        await broadcast_hook(msg)


async def _handle_transition(old: RentalState, new: RentalState, reservation: Reservation | None) -> None:
    global _active_guest_code, _guest_first_entry_logged, _cleaner_present, _last_active_guest
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
        _last_active_guest = guest_name
        # Use phone last 4 as the access code; fall back to random 4-digit PIN
        if reservation and reservation.phone_last4:
            _active_guest_code = reservation.phone_last4
        else:
            _active_guest_code = str(random.randint(1000, 9999))

        _save_state()
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

        notifs = cfg.get("notifications", {})
        n_ci = notifs.get("checkin", {})
        slot_info = f"slot {guest_slot}" if lock_ids else "no lock configured"
        ci_title = _render(n_ci.get("title", "Ready for {guest}"), guest=guest_name)
        ci_msg   = _render(n_ci.get("message", "Check-in tasks done for {guest}. Code {code} set in slot {slot}."),
                           guest=guest_name, code=_active_guest_code, slot=guest_slot)
        if not dry and n_ci.get("enabled", True):
            await notifier.send(notify_svc, ci_title, ci_msg, "str_mgr_checkin")
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
        outgoing = _last_active_guest or guest_name
        notifs = cfg.get("notifications", {})
        if lock_ids:
            if not dry:
                for lid in lock_ids:
                    await lock_manager.clear_code(lid, guest_slot)
            activity_log.add("code_cleared", f"{pfx}Guest code cleared from slot {guest_slot}", outgoing)

        if new == RentalState.CLEANER:
            if lock_ids and cleaner_code:
                if not dry:
                    for lid in lock_ids:
                        await lock_manager.set_code(lid, cleaner_slot, cleaner_code)
                activity_log.add("code_set", f"{pfx}Cleaner code set in slot {cleaner_slot}")
            elif lock_ids:
                activity_log.add("error", f"{pfx}No cleaner PIN configured — cleaner code NOT set. Add one in Settings → Lock.")
            n_co = notifs.get("checkout_cleaner", {})
            co_title = _render(n_co.get("title", "Check-out Complete"), guest=outgoing)
            co_msg   = _render(n_co.get("message", "Check-out tasks done for {guest}. Guest code cleared. Cleaner mode active."), guest=outgoing)
            if not dry and n_co.get("enabled", True):
                await notifier.send(notify_svc, co_title, co_msg, "str_mgr_checkout")
            activity_log.add("checkout", f"{pfx}Check-out tasks done for {outgoing}. Guest code cleared. Cleaner mode active.", outgoing)
        else:
            n_co = notifs.get("checkout_vacant", {})
            co_title = _render(n_co.get("title", "Check-out Complete"), guest=outgoing)
            co_msg   = _render(n_co.get("message", "Check-out tasks done for {guest}. Guest code cleared. Property is vacant."), guest=outgoing)
            if not dry and n_co.get("enabled", True):
                await notifier.send(notify_svc, co_title, co_msg, "str_mgr_checkout")
            activity_log.add("checkout", f"{pfx}Check-out tasks done for {outgoing}. Guest code cleared. Property is vacant.", outgoing)

        _active_guest_code = ""
        _save_state()
        if not dry:
            await automations.trigger(cfg.get("checkout_automation_ids", []))
        elif cfg.get("checkout_automation_ids"):
            activity_log.add("info", f"{pfx}Would trigger {len(cfg['checkout_automation_ids'])} check-out automation(s)")

    await _broadcast({"type": "status_update", "data": get_status()})
    await _broadcast({"type": "log_update", "data": activity_log.recent(5)})


async def poll() -> None:
    """Fetch reservations from all sources, apply manual overrides, then evaluate state."""
    global _reservations, _last_sync
    cfg = settings.load()

    # Test reservations mode: bypass iCal entirely and use manually-created fake bookings
    if cfg.get("enable_test_reservations"):
        fetched = manual_res.to_reservations()
    else:
        # Support both legacy ical_url (single) and ical_urls (list)
        ical_urls: list[str] = cfg.get("ical_urls") or ([cfg["ical_url"]] if cfg.get("ical_url") else [])
        ical_urls = [u for u in ical_urls if u]
        if not ical_urls:
            return

        fetched = []
        seen_uids: set[str] = set()
        any_success = False

        for url in ical_urls:
            try:
                rs = await fetch_reservations(
                    url,
                    cfg.get("default_checkin_time", "15:00"),
                    cfg.get("default_checkout_time", "11:00"),
                    cfg.get("property_timezone", "America/New_York"),
                )
                any_success = True
                for r in rs:
                    if r.uid not in seen_uids:
                        seen_uids.add(r.uid)
                        fetched.append(r)
            except Exception as exc:
                logger.error("iCal fetch failed for %s: %s", url, exc)
                activity_log.add("error", f"Calendar sync failed: {exc}")
                await _broadcast({"type": "log_update", "data": activity_log.recent(5)})

        if not any_success:
            return

        fetched.sort(key=lambda r: r.check_in)

    # Apply manual time overrides here so the state machine, actions,
    # and UI all work from the same effective check-in/out times
    overrides = reservation_overrides.load()
    for r in fetched:
        ov = overrides.get(r.uid) or {}
        try:
            if ov.get("check_in"):
                r.check_in = datetime.fromisoformat(ov["check_in"])
            if ov.get("check_out"):
                r.check_out = datetime.fromisoformat(ov["check_out"])
        except ValueError:
            logger.warning("Ignoring invalid time override for reservation %s", r.uid)

    _reservations = fetched
    _last_sync = datetime.now(timezone.utc)
    await evaluate_state()


async def evaluate_state() -> None:
    """Re-evaluate rental state from cached reservations; runs every minute
    so transitions fire on time instead of waiting for the next iCal fetch."""
    global _state, _active_reservation, _next_reservation
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
        _save_state()
        relevant = active or nxt
        asyncio.create_task(_handle_transition(old_state, new_state, relevant))
    else:
        await _broadcast({"type": "status_update", "data": get_status()})


_lock_nodes: dict[str, int] = {}  # lock entity_id → Z-Wave node_id cache


async def handle_lock_event(event_data: dict[str, Any]) -> None:
    global _guest_first_entry_logged, _cleaner_present
    cfg = settings.load()
    lock_ids = cfg.get("lock_entity_ids", [])
    if not lock_ids:
        return

    # zwave_js_notification payload (per HA docs):
    #   { command_class: 113, type: 6, event: <int>, label: "Access Control",
    #     event_label: "Keypad unlock operation", parameters: {userId: N} }
    # type 6 = Access Control; event 6 = keypad unlock, 1/3/5 = manual/RF/keypad lock
    if event_data.get("command_class") != 113 or event_data.get("type") != 6:
        return

    # Match event node to one of our configured locks (node_id cached per entity)
    event_node = event_data.get("node_id")
    matched = False
    for lid in lock_ids:
        node = _lock_nodes.get(lid)
        if node is None:
            state = await ha_client.get_state(lid)
            node = (state or {}).get("attributes", {}).get("node_id")
            if node is not None:
                _lock_nodes[lid] = node
        if node == event_node:
            matched = True
            break
    if not matched:
        return

    event   = event_data.get("event")
    user_id = (event_data.get("parameters") or {}).get("userId")
    is_keypad_unlock = event == 6
    is_lock_event    = event in {1, 3, 5}

    guest_slot   = cfg.get("guest_code_slot", 2)
    cleaner_slot = cfg.get("cleaner_code_slot", 3)
    notify_svc   = cfg.get("notify_service", "")
    guest_name   = _active_reservation.guest_name if _active_reservation else "Guest"

    notifs = cfg.get("notifications", {})
    if is_keypad_unlock:
        if user_id == guest_slot and not _guest_first_entry_logged:
            _guest_first_entry_logged = True
            _save_state()
            n_ga  = notifs.get("guest_arrived", {})
            msg   = _render(n_ga.get("message", "{guest} has arrived and used their code for the first time."), guest=guest_name)
            title = _render(n_ga.get("title", "Guest Arrived!"), guest=guest_name)
            if n_ga.get("enabled", True):
                await notifier.send(notify_svc, title, msg, "str_mgr_first_entry")
            activity_log.add("first_entry", msg, guest_name)
            await _broadcast({"type": "log_update", "data": activity_log.recent(5)})
        elif user_id == cleaner_slot and not _cleaner_present:
            _cleaner_present = True
            _save_state()
            n_ca  = notifs.get("cleaner_arrived", {})
            msg   = n_ca.get("message", "Cleaner entered the property.")
            title = n_ca.get("title", "Cleaner Arrived")
            if n_ca.get("enabled", True):
                await notifier.send(notify_svc, title, msg, "str_mgr_cleaner_entry")
            activity_log.add("cleaner_entry", msg)
            await _broadcast({"type": "log_update", "data": activity_log.recent(5)})

    elif is_lock_event and _cleaner_present:  # Any lock event while cleaner is inside
        _cleaner_present = False
        _save_state()
        dry = addon_options.test_mode()
        pfx = "[TEST] " if dry else ""
        n_cl  = notifs.get("cleaner_left", {})
        msg   = n_cl.get("message", "Cleaner locked up and left the property.")
        title = n_cl.get("title", "Cleaner Left")
        if not dry and n_cl.get("enabled", True):
            await notifier.send(notify_svc, title, msg, "str_mgr_cleaner_exit")
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
            "next_guest": next_r.guest_name if is_cleaner_after and next_r else None,
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
    _load_state()
    _scheduler.add_job(poll, "interval", minutes=poll_interval_minutes, id="ical_poll", replace_existing=True)
    # Lightweight state re-check every minute so check-in/out transitions
    # fire on time instead of waiting for the next calendar fetch
    _scheduler.add_job(evaluate_state, "interval", minutes=1, id="state_eval", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()
    logger.info("Scheduler started with %d-minute poll interval", poll_interval_minutes)


def restart(poll_interval_minutes: int) -> None:
    _scheduler.reschedule_job("ical_poll", trigger="interval", minutes=poll_interval_minutes)
    logger.info("Scheduler rescheduled to %d-minute interval", poll_interval_minutes)


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
