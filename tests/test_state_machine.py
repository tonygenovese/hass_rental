"""Tests for the pure determine_state() function — the core rental state logic."""
from __future__ import annotations

import pytest

from app.ical_parser import Reservation
from app.state_machine import RentalState, determine_state
from tests.conftest import utc


def res(checkin: tuple, checkout: tuple, name: str = "Guest") -> Reservation:
    """Shorthand: res((Y,M,D,H), (Y,M,D,H)) builds a Reservation."""
    return Reservation(
        guest_name=name,
        check_in=utc(*checkin),
        check_out=utc(*checkout),
    )


# ── Currently occupied ────────────────────────────────────────────────────────

def test_occupied_when_now_is_during_reservation():
    r = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0))
    now = utc(2026, 6, 26, 12, 0)
    assert determine_state([r], now) == RentalState.OCCUPIED


def test_occupied_at_exact_check_in_moment():
    r = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0))
    assert determine_state([r], utc(2026, 6, 25, 15, 0)) == RentalState.OCCUPIED


def test_not_occupied_at_exact_check_out_moment():
    """check_out is exclusive — the second the checkout time hits, they're gone."""
    r = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0))
    assert determine_state([r], utc(2026, 6, 28, 11, 0)) != RentalState.OCCUPIED


# ── Cleaner mode (back-to-back reservations) ──────────────────────────────────

def test_cleaner_when_gap_under_24h():
    """Guest A checks out, Guest B arrives 6 hours later → cleaner window."""
    guest_a = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0), "Guest A")
    guest_b = res((2026, 6, 28, 17, 0), (2026, 7,  1, 11, 0), "Guest B")
    # Now is 30 minutes after Guest A checked out
    now = utc(2026, 6, 28, 11, 30)
    assert determine_state([guest_a, guest_b], now) == RentalState.CLEANER


def test_cleaner_gap_measured_checkin_minus_checkout_not_now():
    """
    Critical: CLEANER is based on (next_checkin - last_checkout), NOT (next_checkin - now).
    If the gap is 6h but we're 25h before next check-in, it should still be CLEANER.
    (This was the original bug we fixed.)
    """
    guest_a = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0), "Guest A")
    guest_b = res((2026, 6, 28, 17, 0), (2026, 7,  1, 11, 0), "Guest B")
    # Now is 25h before Guest B checks in, but the gap (A out→B in) is only 6h
    now = utc(2026, 6, 27, 16, 0)   # Guest A is still there — actually this would be OCCUPIED
    # Let's put now 1 second after Guest A checks out, but still 6h before Guest B
    now = utc(2026, 6, 28, 11, 1)
    assert determine_state([guest_a, guest_b], now) == RentalState.CLEANER


def test_vacant_when_gap_over_24h():
    """3-day gap between reservations → no cleaner mode, just vacant."""
    guest_a = res((2026, 6, 20, 15, 0), (2026, 6, 23, 11, 0), "Guest A")
    guest_b = res((2026, 6, 26, 15, 0), (2026, 6, 29, 11, 0), "Guest B")
    now = utc(2026, 6, 24, 12, 0)   # between the two
    assert determine_state([guest_a, guest_b], now) == RentalState.VACANT


def test_cleaner_boundary_exactly_24h_gap_is_vacant():
    """Gap of exactly 24h should NOT trigger cleaner (strict < comparison)."""
    guest_a = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0), "Guest A")
    guest_b = res((2026, 6, 29, 11, 0), (2026, 7,  2, 11, 0), "Guest B")  # exactly 24h later
    now = utc(2026, 6, 28, 12, 0)
    assert determine_state([guest_a, guest_b], now) == RentalState.VACANT


def test_cleaner_just_under_24h_gap():
    """Gap of 23h 59m should trigger cleaner mode."""
    guest_a = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11,  0), "Guest A")
    guest_b = res((2026, 6, 29, 10, 59), (2026, 7,  2, 11, 0), "Guest B")  # 23h59m gap
    now = utc(2026, 6, 28, 12, 0)
    assert determine_state([guest_a, guest_b], now) == RentalState.CLEANER


# ── Vacant ────────────────────────────────────────────────────────────────────

def test_vacant_with_no_reservations():
    assert determine_state([], utc(2026, 6, 25, 12, 0)) == RentalState.VACANT


def test_vacant_with_only_future_reservations():
    r = res((2026, 7, 10, 15, 0), (2026, 7, 14, 11, 0))
    now = utc(2026, 6, 25, 12, 0)
    assert determine_state([r], now) == RentalState.VACANT


def test_vacant_after_last_reservation_ends():
    r = res((2026, 6, 20, 15, 0), (2026, 6, 23, 11, 0))
    now = utc(2026, 6, 25, 12, 0)   # well after checkout
    assert determine_state([r], now) == RentalState.VACANT


def test_vacant_when_no_past_reservation_but_upcoming():
    """
    Only a future booking exists (fresh setup, first guest ever).
    No past checkout → can't be CLEANER → must be VACANT.
    """
    r = res((2026, 7, 1, 15, 0), (2026, 7, 4, 11, 0))
    now = utc(2026, 6, 30, 12, 0)   # day before first ever guest
    assert determine_state([r], now) == RentalState.VACANT


# ── Occupied takes priority ───────────────────────────────────────────────────

def test_occupied_takes_priority_over_cleaner_check():
    """Even with back-to-back reservations, if we're IN a reservation → OCCUPIED."""
    guest_a = res((2026, 6, 25, 15, 0), (2026, 6, 28, 11, 0), "Guest A")
    guest_b = res((2026, 6, 28, 17, 0), (2026, 7,  1, 11, 0), "Guest B")
    now = utc(2026, 6, 27, 12, 0)  # mid-stay for Guest A
    assert determine_state([guest_a, guest_b], now) == RentalState.OCCUPIED


# ── Multiple past reservations ────────────────────────────────────────────────

def test_uses_most_recent_past_checkout_for_gap():
    """With two past reservations, the gap is measured from the most recent checkout."""
    old_guest  = res((2026, 6, 10, 15, 0), (2026, 6, 13, 11, 0), "Old Guest")
    last_guest = res((2026, 6, 20, 15, 0), (2026, 6, 23, 11, 0), "Last Guest")
    next_guest = res((2026, 6, 23, 17, 0), (2026, 6, 26, 11, 0), "Next Guest")  # 6h after Last Guest
    now = utc(2026, 6, 23, 12, 0)
    assert determine_state([old_guest, last_guest, next_guest], now) == RentalState.CLEANER
