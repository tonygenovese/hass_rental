import json
import os
from typing import Any

SETTINGS_PATH = "/data/settings.json"

DEFAULTS: dict[str, Any] = {
    "ical_url": "",
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
}


def load() -> dict[str, Any]:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULTS)
    with open(SETTINGS_PATH) as f:
        stored = json.load(f)
    merged = {**DEFAULTS, **stored}
    # Migrate single lock_entity_id → lock_entity_ids
    if merged.get("lock_entity_id") and not merged["lock_entity_ids"]:
        merged["lock_entity_ids"] = [merged["lock_entity_id"]]
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
