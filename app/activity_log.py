import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

LOG_PATH = "/data/activity_log.json"
MAX_ENTRIES = 500

LogType = Literal[
    "checkin", "checkout", "first_entry", "cleaner_entry",
    "code_set", "code_cleared", "thermostat", "notify", "info", "error"
]

_entries: list[dict[str, Any]] = []


def _load() -> None:
    global _entries
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            _entries = json.load(f)
    else:
        _entries = []


def _persist() -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump(_entries[-MAX_ENTRIES:], f, indent=2)


def init() -> None:
    _load()


def add(log_type: LogType, message: str, guest: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": log_type,
        "message": message,
        "guest": guest,
    }
    _entries.append(entry)
    if len(_entries) > MAX_ENTRIES:
        _entries.pop(0)
    _persist()
    return entry


def get_page(page: int = 1, limit: int = 50, log_type: str | None = None) -> dict[str, Any]:
    filtered = list(reversed(_entries))
    if log_type and log_type != "all":
        filtered = [e for e in filtered if e["type"] == log_type]
    total = len(filtered)
    start = (page - 1) * limit
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "entries": filtered[start: start + limit],
    }


def recent(n: int = 5) -> list[dict[str, Any]]:
    return list(reversed(_entries))[:n]
