import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from icalendar import Calendar

logger = logging.getLogger(__name__)


@dataclass
class Reservation:
    guest_name: str
    check_in: datetime
    check_out: datetime
    phone_last4: str = field(default="")
    email: str = field(default="")
    adults: int = field(default=0)
    reservation_code: str = field(default="")
    uid: str = field(default="")

    def is_active(self, now: datetime) -> bool:
        return self.check_in <= now < self.check_out

    def hours_until(self, now: datetime) -> float:
        delta = self.check_in - now
        return delta.total_seconds() / 3600


def _get_tz(tz_string: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(tz_string)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning("Unknown timezone %r, falling back to UTC", tz_string)
        return timezone.utc


def _to_datetime(val: date | datetime, fallback_time: time, tz) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=tz)
        return val.astimezone(timezone.utc)
    # Date-only: combine with the fallback time in the property's local timezone
    return datetime.combine(val, fallback_time, tzinfo=tz).astimezone(timezone.utc)


def _parse_time(s: str) -> time | None:
    """Try to parse a time string like '3:00 PM', '15:00', '15:00:00'."""
    s = s.strip()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def _parse_description(desc: str) -> dict:
    """Extract structured guest info from an Airbnb iCal DESCRIPTION."""
    out = {
        "name": "", "phone_last4": "", "email": "",
        "adults": 0, "reservation_code": "",
        "checkin_time": None, "checkout_time": None,
    }
    if not desc:
        return out

    # Normalize all line ending variants
    desc = desc.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    lines = [l.strip() for l in desc.split("\n")]
    first = last = ""

    for line in lines:
        # Airbnb format: "Reservation URL: .../details/HMWXK8PNDB"
        m = re.search(r"reservations/details/([A-Z0-9]+)", line, re.IGNORECASE)
        if m and not out["reservation_code"]:
            out["reservation_code"] = m.group(1).upper()

        # Generic reservation/confirmation code line
        m = re.match(r"(?:reservation|confirmation)\s*(?:code|id)\s*:\s*(\S+)", line, re.IGNORECASE)
        if m and not out["reservation_code"]:
            out["reservation_code"] = m.group(1).strip()

        # Full name
        m = re.match(r"(?:guest\s*name|full\s*name|name|guest)\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not out["name"]:
            candidate = m.group(1).strip()
            if not re.search(r"\d+\s+guest", candidate, re.IGNORECASE):
                out["name"] = candidate

        # First / last name on separate lines
        m = re.match(r"first\s*(?:name)?\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not first:
            first = m.group(1).strip()
        m = re.match(r"last\s*(?:name)?\s*:\s*(.+)", line, re.IGNORECASE)
        if m and not last:
            last = m.group(1).strip()

        # Phone — "phone[anything]:" handles "Phone Number (Last 4 Digits):"
        m = re.search(r"phone[^:]*:\s*([\d\s\-\+\(\)\.x]+)", line, re.IGNORECASE)
        if m and not out["phone_last4"]:
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) >= 4:
                out["phone_last4"] = digits[-4:]
            elif len(digits) > 0:
                out["phone_last4"] = digits  # already just the last 4

        # Email
        m = re.search(r"email\s*:\s*(\S+@\S+)", line, re.IGNORECASE)
        if m and not out["email"]:
            out["email"] = m.group(1).strip()

        # Adults / guests count
        m = re.match(r"(?:adults|guests)\s*:\s*(\d+)", line, re.IGNORECASE)
        if m and not out["adults"]:
            out["adults"] = int(m.group(1))

        # Check-in/out times if present in description
        m = re.match(r"check[\s\-]?in\s*:\s*.+?(?:at\s+)?([\d:]+\s*(?:AM|PM)?)\s*$", line, re.IGNORECASE)
        if m and out["checkin_time"] is None:
            out["checkin_time"] = _parse_time(m.group(1))

        m = re.match(r"check[\s\-]?out\s*:\s*.+?(?:at\s+)?([\d:]+\s*(?:AM|PM)?)\s*$", line, re.IGNORECASE)
        if m and out["checkout_time"] is None:
            out["checkout_time"] = _parse_time(m.group(1))

    if not out["name"] and (first or last):
        out["name"] = f"{first} {last}".strip()

    return out


async def fetch_reservations(
    ical_url: str,
    default_checkin: str = "15:00",
    default_checkout: str = "11:00",
    property_timezone: str = "UTC",
) -> list[Reservation]:
    default_checkin_time  = time.fromisoformat(default_checkin)
    default_checkout_time = time.fromisoformat(default_checkout)
    tz = _get_tz(property_timezone)

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

        uid  = str(component.get("UID", ""))
        desc = str(component.get("DESCRIPTION", ""))
        info = _parse_description(desc)

        # Use times from description if found, else use settings defaults
        checkin_time  = info["checkin_time"]  or default_checkin_time
        checkout_time = info["checkout_time"] or default_checkout_time

        check_in  = _to_datetime(dtstart.dt, checkin_time, tz)
        check_out = _to_datetime(dtend.dt, checkout_time, tz)

        if info["name"]:
            guest_name = info["name"]
        elif info["reservation_code"]:
            # Airbnb doesn't include guest names — use reservation code
            guest_name = info["reservation_code"]
        else:
            guest_name = re.sub(
                r"^(Reserved\s*[-–]?\s*|Airbnb\s*[-–]?\s*)", "", summary, flags=re.IGNORECASE
            ).strip() or summary

        reservations.append(Reservation(
            guest_name=guest_name,
            check_in=check_in,
            check_out=check_out,
            phone_last4=info["phone_last4"],
            email=info["email"],
            adults=info["adults"],
            reservation_code=info["reservation_code"],
            uid=uid,
        ))

    reservations.sort(key=lambda r: r.check_in)
    logger.debug("Fetched %d reservations from iCal", len(reservations))
    return reservations
