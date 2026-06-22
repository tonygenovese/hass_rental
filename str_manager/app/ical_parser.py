import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

import aiohttp
from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class Reservation:
    guest_name: str
    check_in: datetime
    check_out: datetime

    def is_active(self, now: datetime) -> bool:
        return self.check_in <= now < self.check_out

    def hours_until(self, now: datetime) -> float:
        delta = self.check_in - now
        return delta.total_seconds() / 3600


def _to_datetime(val: date | datetime, fallback_time: time, tz: timezone) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=tz)
        return val.astimezone(tz)
    return datetime.combine(val, fallback_time, tzinfo=tz)


async def fetch_reservations(
    ical_url: str,
    default_checkin: str = "15:00",
    default_checkout: str = "11:00",
) -> list[Reservation]:
    checkin_time = time.fromisoformat(default_checkin)
    checkout_time = time.fromisoformat(default_checkout)
    tz = timezone.utc

    async with aiohttp.ClientSession() as session:
        async with session.get(ical_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            content = await resp.read()

    cal = Calendar.from_ical(content)
    reservations: list[Reservation] = []

    for component in cal.walk("VEVENT"):
        summary = str(component.get("SUMMARY", "")).strip()
        if not summary or summary.upper() in ("BLOCKED", "NOT AVAILABLE", "AIRBNB (NOT AVAILABLE)"):
            continue

        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")
        if not dtstart or not dtend:
            continue

        check_in = _to_datetime(dtstart.dt, checkin_time, tz)
        check_out = _to_datetime(dtend.dt, checkout_time, tz)

        # Strip "Reserved - " prefix Airbnb sometimes prepends
        guest_name = summary.removeprefix("Reserved - ").strip()

        reservations.append(Reservation(
            guest_name=guest_name,
            check_in=check_in,
            check_out=check_out,
        ))

    reservations.sort(key=lambda r: r.check_in)
    logger.debug("Fetched %d reservations from iCal", len(reservations))
    return reservations
