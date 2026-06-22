import json
import os
from typing import Any

SETTINGS_PATH = "/data/settings.json"

DEFAULTS: dict[str, Any] = {
    "ical_url": "",
    "poll_interval_minutes": 30,
    "default_checkin_time": "15:00",
    "default_checkout_time": "11:00",
    "lock_entity_id": "",
    "guest_code_slot": 2,
    "cleaner_code_slot": 3,
    "cleaner_code": "",
    "thermostat_entity_id": "",
    "guest_temp": 72,
    "away_temp": 65,
    "notify_service": "mobile_app",
    "checkin_automation_ids": [],
    "checkout_automation_ids": [],
}


def load() -> dict[str, Any]:
    if not os.path.exists(SETTINGS_PATH):
        return dict(DEFAULTS)
    with open(SETTINGS_PATH) as f:
        stored = json.load(f)
    return {**DEFAULTS, **stored}


def save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


def masked(data: dict[str, Any]) -> dict[str, Any]:
    """Return settings with cleaner_code masked for API responses."""
    out = dict(data)
    if out.get("cleaner_code"):
        out["cleaner_code"] = "••••"
    return out
