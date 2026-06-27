import json
import os
from typing import Any

SETTINGS_PATH = "/data/settings.json"

_NOTIF_DEFAULTS: dict[str, Any] = {
    "checkin": {
        "enabled": True,
        "title": "Ready for {guest}",
        "message": "Check-in tasks done for {guest}. Code {code} set in slot {slot}.",
    },
    "checkout_vacant": {
        "enabled": True,
        "title": "Check-out Complete",
        "message": "Check-out tasks done for {guest}. Guest code cleared. Property is vacant.",
    },
    "checkout_cleaner": {
        "enabled": True,
        "title": "Check-out Complete",
        "message": "Check-out tasks done for {guest}. Guest code cleared. Cleaner mode active.",
    },
    "guest_arrived": {
        "enabled": True,
        "title": "Guest Arrived!",
        "message": "{guest} has arrived and used their code for the first time.",
    },
    "cleaner_arrived": {
        "enabled": True,
        "title": "Cleaner Arrived",
        "message": "Cleaner entered the property.",
    },
    "cleaner_left": {
        "enabled": True,
        "title": "Cleaner Left",
        "message": "Cleaner locked up and left the property.",
    },
}

DEFAULTS: dict[str, Any] = {
    "ical_urls": [],
    "enable_test_reservations": False,
    "poll_interval_minutes": 30,
    "property_timezone": "America/New_York",
    "default_checkin_time": "15:00",
    "default_checkout_time": "11:00",
    "lock_entity_ids": [],
    "guest_code_slot": 2,
    "cleaner_code_slot": 3,
    "cleaner_code": "",
    "notify_service": "",
    "checkin_automation_ids": [],
    "checkout_automation_ids": [],
    "pre_checkin_automation_ids": [],
    "thermostat_entity_ids": [],
    "water_valve_entity_id": "",
    "notifications": _NOTIF_DEFAULTS,
}


def load() -> dict[str, Any]:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULTS)
    with open(SETTINGS_PATH) as f:
        stored = json.load(f)
    merged = {**DEFAULTS, **stored}
    # Deep-merge notifications so new keys get defaults and existing keys get per-field updates
    stored_notifs = stored.get("notifications", {})
    merged["notifications"] = {}
    for key, default_val in _NOTIF_DEFAULTS.items():
        stored_val = stored_notifs.get(key, {})
        merged["notifications"][key] = {**default_val, **stored_val}
    # Migrate legacy ical_url (single string) → ical_urls (list)
    if merged.get("ical_url") and not merged.get("ical_urls"):
        merged["ical_urls"] = [merged["ical_url"]]
    merged.pop("ical_url", None)
    # Migrate single lock_entity_id → lock_entity_ids
    if merged.get("lock_entity_id") and not merged["lock_entity_ids"]:
        merged["lock_entity_ids"] = [merged["lock_entity_id"]]
    # Migrate single thermostat_entity_id → thermostat_entity_ids
    if merged.get("thermostat_entity_id") and not merged.get("thermostat_entity_ids"):
        merged["thermostat_entity_ids"] = [merged["thermostat_entity_id"]]
    for k in ("lock_entity_id", "thermostat_entity_id", "guest_temp", "away_temp"):
        merged.pop(k, None)
    return merged


def save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def masked(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    if out.get("cleaner_code"):
        out["cleaner_code"] = "••••"
    return out
