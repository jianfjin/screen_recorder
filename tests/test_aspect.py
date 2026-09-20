import pytest

from app.aspect import ASPECTS, MIN_SHORT_SIDE, Region, move_region, resize_region_to_ratio, snap_to_ratio

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

# --- appended for U1: pure region editing helpers ---------------------------


def test_move_region_keeps_size_and_shifts_position():
    r = move_region(Region(400, 300, 640, 360), 100, 0, SCREEN_W, SCREEN_H)
    assert (r.x, r.y, r.w, r.h) == (500, 300, 640, 360)


def test_move_region_clamps_to_screen_on_every_edge():
    big = Region(100, 100, 640, 360)
    left = move_region(big, -1000, 0, SCREEN_W, SCREEN_H)
    assert left.x == 0 and (left.w, left.h) == (640, 360)

    up = move_region(big, 0, -1000, SCREEN_W, SCREEN_H)
    assert up.y == 0 and (up.w, up.h) == (640, 360)

    right = move_region(big, SCREEN_W, 0, SCREEN_W, SCREEN_H)
    assert right.x == SCREEN_W - 640
    down = move_region(big, 0, SCREEN_H, SCREEN_W, SCREEN_H)
    assert down.y == SCREEN_H - 360


def _corner_point(r, key):
    """Absolute position of region r's corner named key ("tl".."br")."""
    return (r.x + (0 if key[1] == "l" else r.w), r.y + (0 if key[0] == "t" else r.h))


_OPPPOSITE = {"br": "tl", "bl": "tr", "tr": "bl", "tl": "br"}
_PULL_OUTWARD = {"br": (200, 200), "bl": (-200, 200), "tr": (200, -200), "tl": (-200, -200)}


@pytest.mark.parametrize("aspect,ratio", [("16:9", 16 / 9), ("3:2", 3 / 2)])
@pytest.mark.parametrize("corner", ["br", "bl", "tr", "tl"])
def test_resize_anchors_opposite_corner_and_locks_ratio(aspect, ratio, corner):
    base = Region(200, 200, 640, 360) if aspect == "16:9" else Region(200, 200, 540, 360)
    grabbed = _corner_point(base, corner)
    dx, dy = _PULL_OUTWARD[corner]

    r = resize_region_to_ratio(base, corner, grabbed[0] + dx, grabbed[1] + dy,
                               aspect, SCREEN_W, SCREEN_H)

    anchor = _corner_point(base, _OPPPOSITE[corner])
    ax = r.x if corner[1] == "r" else r.x + r.w
    ay = r.y if corner[0] == "b" else r.y + r.h
    assert (ax, ay) == anchor, "the opposite corner must stay exactly put"
    assert r.w / r.h == pytest.approx(ratio, rel=0.01)
    assert r.w > base.w and r.h > base.h


@pytest.mark.parametrize("aspect,ratio", [("16:9", 16 / 9), ("3:2", 3 / 2)])
def test_resize_inward_past_minimum_stops_at_min_short_side(aspect, ratio):
    num, den = ASPECTS[aspect]
    base = Region(400, 300, 640, round(640 * den / num))
    r = resize_region_to_ratio(base, "br", 410, 305, aspect, SCREEN_W, SCREEN_H)
    assert min(r.w, r.h) >= MIN_SHORT_SIDE
    assert r.w / r.h == pytest.approx(ratio, rel=0.01)


@pytest.mark.parametrize("aspect,ratio", [("16:9", 16 / 9), ("3:2", 3 / 2)])
def test_resize_off_screen_shrinks_but_never_slides_the_anchor(aspect, ratio):
    # Literal snap_to_ratio reuse is the known trap here: from this anchor it
    # returns y=90, i.e. the anchor slides and a resize becomes a move.
    num, den = ASPECTS[aspect]
    base = Region(1000, 900, 200, round(200 * den / num))
    r = resize_region_to_ratio(base, "br", SCREEN_W, SCREEN_H, aspect, SCREEN_W, SCREEN_H)
    assert (r.x, r.y) == (1000, 900)
    assert r.y + r.h <= SCREEN_H and r.x + r.w <= SCREEN_W
    assert r.w / r.h == pytest.approx(ratio, rel=0.01)


def test_resize_driven_by_the_longer_side_for_a_lopsided_pointer():
    # Pointer far right but barely down: width drives the solve, height follows.
    r = resize_region_to_ratio(Region(0, 0, 640, 360), "br", 3000, 12, "16:9", SCREEN_W, SCREEN_H)
    assert (r.x, r.y) == (0, 0)
    assert r.w / r.h == pytest.approx(16 / 9, rel=0.01)
    assert r.h <= SCREEN_H


def test_resize_from_a_flush_screen_corner_stays_on_screen():
    base = Region(0, 0, 1280, 720)
    r = resize_region_to_ratio(base, "tl", -500, -500, "16:9", SCREEN_W, SCREEN_H)
    assert r.x >= 0 and r.y >= 0
    assert r.w / r.h == pytest.approx(16 / 9, rel=0.01)
    # the opposite (bottom-right) corner is the anchor and must not move
    assert (r.x + r.w, r.y + r.h) == (1280, 720)
