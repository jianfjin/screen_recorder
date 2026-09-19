"""SelectionModel is the pure, testable core of the region selector.

U3: two-phase selection. A drag produces a *provisional* region that stays
visible on the overlay; a subsequent click (or Enter/Space) confirms it and
only then is it emitted to the controller. Esc / right-click cancels.

The QWidget surface (RegionOverlay) needs a live X display; it is covered by
the manual smoke test. Here we test the selection state machine directly.
"""
import pytest

from app.aspect import MIN_SHORT_SIDE
from app.overlay import SelectionModel

SW, SH = 3440, 1440


def drag(m, x0, y0, x1, y1):
    m.press(x0, y0)
    m.move(x1, y1)
    return m.release(x1, y1)


def test_drag_yields_unconfirmed_provisional():
    m = SelectionModel("16:9", SW, SH)
    region, confirmed = drag(m, 100, 100, 1100, 200)
    assert confirmed is False
    assert region is not None
    assert (region.x, region.y) == (100, 100)
    assert region.w / region.h == pytest.approx(16 / 9, abs=0.01)


def test_provisional_region_stays_visible_after_release():
    m = SelectionModel("16:9", SW, SH)
    drag(m, 100, 100, 1100, 200)
    assert m.region is not None


def test_click_confirms_provisional():
    m = SelectionModel("16:9", SW, SH)
    region, confirmed = drag(m, 100, 100, 1100, 200)
    assert confirmed is False
    m.press(1100, 200)
    confirmed_region, confirmed = m.release(1101, 201)  # tiny displacement = click
    assert confirmed is True
    assert confirmed_region == region


def test_click_without_provisional_is_noop():
    m = SelectionModel("16:9", SW, SH)
    m.press(100, 100)
    region, confirmed = m.release(102, 101)
    assert region is None
    assert confirmed is False
    assert m.region is None


def test_redrag_replaces_provisional():
    m = SelectionModel("16:9", SW, SH)
    drag(m, 100, 100, 1100, 200)
    region, confirmed = drag(m, 2000, 300, 2600, 400)
    assert confirmed is False
    assert (region.x, region.y) == (2000, 300)
    assert m.region == region


def test_confirm_via_keyboard_returns_provisional():
    m = SelectionModel("16:9", SW, SH)
    region, _ = drag(m, 100, 100, 1100, 200)
    assert m.confirm() == region


def test_confirm_without_provisional_is_none():
    m = SelectionModel("16:9", SW, SH)
    assert m.confirm() is None


def test_cancel_clears_provisional():
    m = SelectionModel("16:9", SW, SH)
    drag(m, 100, 100, 1100, 200)
    assert m.region is not None
    m.cancel()
    assert m.region is None
    assert m.confirm() is None
    m.press(100, 100)
    assert m.release(101, 101) == (None, False)


def test_release_without_press_is_noop():
    m = SelectionModel("16:9", SW, SH)
    assert m.release(10, 10) == (None, False)


def test_tiny_drag_hits_min_size():
    m = SelectionModel("16:9", SW, SH)
    region, confirmed = drag(m, 500, 500, 512, 506)  # small drag, above click threshold
    assert region is not None and confirmed is False
    assert min(region.w, region.h) >= MIN_SHORT_SIDE


def test_clamped_to_screen():
    m = SelectionModel("16:9", SW, SH)
    region, _ = drag(m, 3400, 1400, 100, 100)
    assert region is not None
    assert 0 <= region.x and 0 <= region.y
    assert region.x + region.w <= SW
    assert region.y + region.h <= SH


def test_change_aspect_mid_idle():
    m = SelectionModel("16:9", SW, SH)
    m.set_aspect("3:2")
    region, _ = drag(m, 0, 0, 300, 200)
    assert region is not None
    assert region.w / region.h == pytest.approx(3 / 2, abs=0.05)
