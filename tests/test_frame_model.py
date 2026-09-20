"""RegionFrameModel — the pure interaction core of the persistent region frame.

Where SelectionModel covers "draw a new region" (two-phase, modal), this model
covers "edit a region that already exists": grab the border band to move the
whole frame, grab a corner handle to rescale it under the locked aspect.

No Qt types on purpose, so all of the geometry is testable offscreen. Whether
the real window lets clicks through its hollow centre cannot be proved here;
that is the manual / live-X check in the plan's Verification Contract.
"""
import pytest

from app.aspect import MIN_SHORT_SIDE, Region
from app.frame import MOVE, RegionFrameModel

SCREEN_W, SCREEN_H = 3440, 1440
BASE = Region(400, 300, 640, 360)


def model(region=BASE, aspect="16:9"):
    return RegionFrameModel(region, aspect, SCREEN_W, SCREEN_H)


def drag(m, x0, y0, x1, y1):
    m.press(x0, y0)
    preview = m.move(x1, y1)
    return preview, m.release(x1, y1)


def test_drag_on_the_band_moves_the_whole_region():
    m = model()
    _, settled = drag(m, 400 + 320, 300, 400 + 320 + 200, 480)  # mid top band: +200 right, +180 down
    assert settled == Region(600, 480, 640, 360)
    assert m.region == settled


def test_drag_on_a_corner_handle_rescales_under_the_locked_aspect():
    m = model()
    _, settled = drag(m, 1040, 660, 1340, 830)  # bottom-right handle, outward
    assert settled.x == BASE.x and settled.y == BASE.y
    assert settled.w / settled.h == pytest.approx(16 / 9, rel=0.01)
    assert settled.w > BASE.w and settled.h > BASE.h


@pytest.mark.parametrize("corner,point", [
    ("tl", (400, 300)), ("tr", (1040, 300)), ("bl", (400, 660)), ("br", (1040, 660)),
])
def test_press_inside_the_grab_radius_is_a_resize_not_a_move(corner, point):
    m = model()
    m.press(*point)
    assert m.mode[0] == "resize" and m.mode[1] == corner


def test_just_outside_the_grab_radius_is_a_move():
    m = model()
    m.press(1040 + RegionFrameModel.CORNER_GRAB_PX + 1, 660)
    assert m.mode[0] == MOVE


def test_exactly_at_the_grab_radius_still_resizes():
    m = model()
    m.press(1040 + RegionFrameModel.CORNER_GRAB_PX, 660)
    assert m.mode[0] == "resize"


def test_release_without_a_press_is_a_noop():
    m = model()
    assert m.move(900, 700) == BASE
    assert m.release(900, 700) is None


def test_release_without_movement_reports_no_change():
    m = model()
    preview, settled = drag(m, 700, 300, 700, 300)
    assert preview == BASE
    assert settled is None


def test_move_is_relative_to_the_press_point_not_the_cursor():
    # Grabbing the band 200px into the frame must not teleport the frame.
    m = model()
    _, settled = drag(m, 900, 300, 950, 340)
    assert settled == Region(450, 340, 640, 360)


def test_preview_follows_the_pointer_before_release():
    m = model()
    m.press(700, 300)
    assert m.move(800, 300) == Region(500, 300, 640, 360)
    assert m.region == Region(500, 300, 640, 360)
    assert m.dragging is True


def test_cancelled_drag_leaves_the_region_untouched():
    m = model()
    m.press(700, 300)
    m.move(900, 500)
    m.cancel()
    assert m.region == BASE
    assert m.dragging is False


def test_resize_toward_the_anchor_stops_at_the_minimum_instead_of_flipping():
    m = model()
    _, settled = drag(m, 1040, 660, 20, 20)  # sweep the handle past the anchor
    assert settled is not None
    assert min(settled.w, settled.h) >= MIN_SHORT_SIDE
    assert (settled.x, settled.y) == (BASE.x, BASE.y)
    assert settled.w / settled.h == pytest.approx(16 / 9, rel=0.01)


def test_moved_region_is_clamped_so_the_frame_never_leaves_the_screen():
    m = model()
    _, settled = drag(m, 700, 400, SCREEN_W + 5000, 400)
    assert settled.x + settled.w == SCREEN_W
    assert settled.y == BASE.y


def test_3_2_aspect_is_respected_on_resize():
    m = model(Region(400, 300, 540, 360), "3:2")
    _, settled = drag(m, 940, 660, 1240, 860)
    assert settled.w / settled.h == pytest.approx(3 / 2, rel=0.01)


def test_region_flush_with_the_screen_corner_is_still_editable():
    m = model(Region(0, 0, 1280, 720))
    _, settled = drag(m, 1280, 720, 1680, 940)  # bottom-right handle outward
    assert (settled.x, settled.y) == (0, 0)
    assert settled.y + settled.h <= SCREEN_H
    assert settled.w / settled.h == pytest.approx(16 / 9, rel=0.01)


def test_model_never_rejects_for_a_locked_state():
    # Locking is the controller's call (KTD4): the model always computes geometry.
    m = model()
    _, settled = drag(m, 700, 300, 900, 400)
    assert settled is not None and hasattr(settled, "w")
