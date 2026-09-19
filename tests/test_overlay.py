"""SelectionModel is the pure, testable core of the region selector.

The QWidget surface (RegionOverlay) needs a live X display; it is covered by
the U5 manual smoke test. Here we test the drag state machine directly.
"""
from app.aspect import MIN_SHORT_SIDE
from app.overlay import SelectionModel

SW, SH = 3440, 1440


def test_release_returns_16_9_region():
    m = SelectionModel("16:9", SW, SH)
    m.press(100, 100)
    m.move(1100, 200)          # raw 1000x100 -> width-driven
    r = m.release()
    assert r is not None
    assert r.w / r.h == 1000 / (1000 * 9 / 16) or abs(r.w / r.h - 16 / 9) < 0.01
    assert (r.x, r.y) == (100, 100)


def test_release_after_cancel_is_none():
    m = SelectionModel("3:2", SW, SH)
    m.press(100, 100)
    m.move(400, 500)
    m.cancel()
    assert m.region is None
    assert m.release() is None


def test_release_without_move_is_none():
    m = SelectionModel("16:9", SW, SH)
    m.press(100, 100)
    assert m.release() is None


def test_state_resets_after_release():
    m = SelectionModel("16:9", SW, SH)
    m.press(100, 100)
    m.move(1100, 200)
    m.release()
    assert m.dragging is False
    assert m.region is None


def test_clamped_to_screen():
    m = SelectionModel("16:9", SW, SH)
    m.press(3400, 1400)
    m.move(100, 100)
    r = m.release()
    assert r is not None
    assert 0 <= r.x and 0 <= r.y
    assert r.x + r.w <= SW
    assert r.y + r.h <= SH


def test_tiny_drag_hits_min_size():
    m = SelectionModel("16:9", SW, SH)
    m.press(500, 500)
    m.move(503, 502)
    r = m.release()
    assert r is not None
    assert min(r.w, r.h) >= MIN_SHORT_SIDE


def test_change_aspect_mid_idle():
    m = SelectionModel("16:9", SW, SH)
    m.set_aspect("3:2")
    m.press(0, 0)
    m.move(300, 200)
    r = m.release()
    assert r is not None
    assert abs(r.w / r.h - 3 / 2) < 0.01
