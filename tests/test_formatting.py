"""Pure elapsed-time formatting (U1 / R2 / AE2).

`format_duration(seconds)` is the single source of truth for the on-screen
elapsed-time label. Kept pure (no Qt) so it is trivially unit-testable.
"""
from app.formatting import format_duration


def test_zero():
    assert format_duration(0) == "00:00"
    assert format_duration(0.0) == "00:00"


def test_under_a_minute_is_mm_ss():
    assert format_duration(5) == "00:05"
    assert format_duration(59) == "00:59"


def test_carries_minutes():
    assert format_duration(65) == "01:05"


def test_floors_fractional_seconds():
    # 3599.9s is still "59:59", not "01:00:00".
    assert format_duration(3599.9) == "59:59"


def test_hour_boundary_switches_to_hh_mm_ss():
    assert format_duration(3600) == "01:00:00"


def test_over_an_hour():
    assert format_duration(3661) == "01:01:01"
    assert format_duration(90061) == "25:01:01"
