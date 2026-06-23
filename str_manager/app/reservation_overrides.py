import json
import os
from typing import Any

OVERRIDES_PATH = "/data/reservation_overrides.json"


def load() -> dict[str, Any]:
    try:
        with open(OVERRIDES_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def get(uid: str) -> dict[str, Any]:
    return load().get(uid, {})


def set_times(uid: str, check_in: str | None = None, check_out: str | None = None) -> None:
    data = load()
    entry = data.setdefault(uid, {})
    if check_in is not None:
        entry["check_in"] = check_in
    if check_out is not None:
        entry["check_out"] = check_out
    os.makedirs(os.path.dirname(OVERRIDES_PATH), exist_ok=True)
    with open(OVERRIDES_PATH, "w") as f:
        json.dump(data, f, indent=2)
