from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ical_parser import Reservation


class RentalState(str, Enum):
    VACANT = "vacant"
    OCCUPIED = "occupied"
    CLEANER = "cleaner"


CLEANER_GAP_HOURS = 24


def determine_state(reservations: list[Reservation], now: datetime) -> RentalState:
    """Pure function: compute rental state from reservation list and current time."""
    active = next((r for r in reservations if r.is_active(now)), None)
    if active:
        return RentalState.OCCUPIED

    past = [r for r in reservations if r.check_out <= now]
    last_ended = max(past, key=lambda r: r.check_out, default=None)
    future = [r for r in reservations if r.check_in > now]
    nxt = future[0] if future else None

    if last_ended and nxt and (nxt.check_in - last_ended.check_out) < timedelta(hours=CLEANER_GAP_HOURS):
        return RentalState.CLEANER
    return RentalState.VACANT
