import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone

import aiohttp
from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class Reservation:
    guest_name: str
    check_in: datetime
    check_out: datetime
    phone_last4: str = field(default="")

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


def _parse_description(desc: str) -> tuple[str, str]:
    """Extract (guest_name, phone_last4) from an Airbnb iCal DESCRIPTION."""
    if not desc:
        return "", ""

    # Normalize line endings and escaped newlines from iCal encoding
    desc = desc.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    lines = [l.strip() for l in desc.split("\n")]

    name = ""
    first = ""
    last = ""
    phone_last4 = ""

    for line in lines:
        # Full name patterns: "Guest Name: John Smith", "Name: John Smith", "Guest: John Smith"
        m = re.match(r"(?:guest\s*name|full\s*name|name|guest)\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not name:
            candidate = m.group(1).strip()
            # Skip if it looks like metadata (e.g. "Name: 2 guests")
            if not re.search(r"\d+\s+guest", candidate, re.IGNORECASE):
                name = candidate

        # First / last name split
        m = re.match(r"first\s*(?:name)?\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not first:
            first = m.group(1).strip()
        m = re.match(r"last\s*(?:name)?\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not last:
            last = m.group(1).strip()

        # Phone: extract last 4 digits
        m = re.search(r"phone(?:\s*number)?\s*:\s*([\d\s\-\+\(\)\.x]+)", line, re.IGNORECASE)
        if m and not phone_last4:
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) >= 4:
                phone_last4 = digits[-4:]

    if not name and (first or last):
        name = f"{first} {last}".strip()

    return name, phone_last4


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
        dtend   = component.get("DTEND")
        if not dtstart or not dtend:
            continue

        check_in  = _to_datetime(dtstart.dt, checkin_time, tz)
        check_out = _to_datetime(dtend.dt, checkout_time, tz)

        desc = str(component.get("DESCRIPTION", ""))
        name_from_desc, phone_last4 = _parse_description(desc)

        if name_from_desc:
            guest_name = name_from_desc
        else:
            # Strip Airbnb prefixes from SUMMARY as fallback
            guest_name = re.sub(r"^(Reserved\s*[-–]?\s*|Airbnb\s*[-–]?\s*)", "", summary, flags=re.IGNORECASE).strip()
            if not guest_name:
                guest_name = summary

        reservations.append(Reservation(
            guest_name=guest_name,
            check_in=check_in,
            check_out=check_out,
            phone_last4=phone_last4,
        ))

    reservations.sort(key=lambda r: r.check_in)
    logger.debug("Fetched %d reservations from iCal", len(reservations))
    return reservations
