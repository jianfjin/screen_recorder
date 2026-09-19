import pytest

from app.aspect import MIN_SHORT_SIDE, snap_to_ratio

SCREEN_W, SCREEN_H = 3440, 1440


def _ratio(r):
    return r.w / r.h


def test_16_9_wide_drag_locks_ratio():
    r = snap_to_ratio(100, 100, 1100, 200, "16:9", SCREEN_W, SCREEN_H)
    assert _ratio(r) == pytest.approx(16 / 9, rel=0.01)


def test_16_9_tall_drag_locks_ratio():
    r = snap_to_ratio(100, 100, 200, 1100, "16:9", SCREEN_W, SCREEN_H)
    assert _ratio(r) == pytest.approx(16 / 9, rel=0.01)


def test_3_2_drag_locks_ratio():
    r = snap_to_ratio(100, 100, 400, 500, "3:2", SCREEN_W, SCREEN_H)
    assert _ratio(r) == pytest.approx(3 / 2, rel=0.01)


def test_anchored_at_start_and_extends_toward_cursor():
    # A drag that fits comfortably on screen, anchored at the start corner.
    r = snap_to_ratio(50, 50, 500, 300, "16:9", SCREEN_W, SCREEN_H)
    assert (r.x, r.y) == (50, 50)
    assert r.w > 0 and r.h > 0
    assert _ratio(r) == pytest.approx(16 / 9, rel=0.01)


def test_clamped_to_screen_bounds():
    r = snap_to_ratio(3400, 1400, 100, 100, "16:9", SCREEN_W, SCREEN_H)
    assert 0 <= r.x and 0 <= r.y
    assert r.x + r.w <= SCREEN_W
    assert r.y + r.h <= SCREEN_H


def test_region_that_overflows_screen_is_shrunk():
    # Region as tall as the screen cannot be anchored at y=50; it clamps to y=0.
    r = snap_to_ratio(50, 50, 3400, 1400, "16:9", SCREEN_W, SCREEN_H)
    assert r.y == 0
    assert r.x + r.w <= SCREEN_W and r.y + r.h <= SCREEN_H


def test_min_size_for_tiny_drag():
    r = snap_to_ratio(500, 500, 503, 502, "16:9", SCREEN_W, SCREEN_H)
    assert min(r.w, r.h) >= MIN_SHORT_SIDE
    assert r.w > 0 and r.h > 0


def test_negative_direction_drag_clamped():
    # Anchor bottom-right, drag up/left -> extends up/left, clamped to screen.
    r = snap_to_ratio(2000, 2000, 1900, 1100, "16:9", SCREEN_W, SCREEN_H)
    assert (r.x, r.y, r.w, r.h) == (400, 540, 1600, 900)
