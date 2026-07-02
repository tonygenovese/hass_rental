import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from .ical_parser import Reservation

TEST_RES_PATH = "/data/test_reservations.json"
logger = logging.getLogger(__name__)


def load_raw() -> list[dict[str, Any]]:
    try:
        with open(TEST_RES_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.error("Failed to load test reservations: %s", exc)
        return []


def save_raw(reservations: list[dict[str, Any]]) -> None:
    with open(TEST_RES_PATH, "w") as f:
        json.dump(reservations, f, indent=2)


def add(guest_name: str, check_in: str, check_out: str) -> dict[str, Any]:
    rs = load_raw()
    entry: dict[str, Any] = {
        "uid": str(uuid.uuid4()),
        "guest_name": guest_name,
        "check_in": check_in,
        "check_out": check_out,
    }
    rs.append(entry)
    rs.sort(key=lambda r: r["check_in"])
    save_raw(rs)
    return entry


def remove(uid: str) -> bool:
    rs = load_raw()
    new_rs = [r for r in rs if r.get("uid") != uid]
    if len(new_rs) == len(rs):
        return False
    save_raw(new_rs)
    return True


def clear() -> None:
    save_raw([])


def to_reservations() -> list[Reservation]:
    result = []
    for item in load_raw():
        try:
            ci = datetime.fromisoformat(item["check_in"])
            co = datetime.fromisoformat(item["check_out"])
            if ci.tzinfo is None:
                ci = ci.replace(tzinfo=timezone.utc)
            if co.tzinfo is None:
                co = co.replace(tzinfo=timezone.utc)
            result.append(Reservation(
                guest_name=item.get("guest_name", "Test Guest"),
                check_in=ci,
                check_out=co,
                uid=item.get("uid", str(uuid.uuid4())),
            ))
        except Exception as exc:
            logger.warning("Skipping malformed test reservation: %s", exc)
    return sorted(result, key=lambda r: r.check_in)
