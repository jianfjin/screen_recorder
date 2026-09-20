"""Persistent region frame: visibility, geometry, and the wiring around it.

Offscreen (QT_QPA_PLATFORM from tests/conftest.py). These prove the *wiring* -
who shows and hides the frame, what geometry it takes, and that region writes
all pass the controller's single gate. Whether the hollow centre really lets
clicks through to the window underneath cannot be proven offscreen; that is the
live-X row in the plan's Verification Contract.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication

from app.aspect import Region
from app.controller import RecordingController, State
from app.frame import RegionFrame

SCREEN_W, SCREEN_H = 3440, 1440
R = Region(400, 300, 640, 360)


class FakeRecorder:
    def __init__(self, args):
        self.args = args
        self.started = False

    def start(self):
        self.started = True

    def stop(self, *a, **k):
        pass

    @property
    def running(self):
        return self.started


@pytest.fixture
def controller():
    QApplication.instance()

    def make_recorder(region, aspect, out_path, with_audio, display=None):
        created["rec"] = FakeRecorder((region, aspect, out_path, with_audio))
        return created["rec"]

    created = {}
    c = RecordingController(make_recorder=make_recorder,
                            audio_available=lambda: True,
                            make_path=lambda base_dir=None: "/tmp/sr_test.mp4")
    c.created = created
    return c


@pytest.fixture
def frame(qapp):
    f = RegionFrame(SCREEN_W, SCREEN_H)
    yield f
    f.deleteLater()


# -- display / hide rules ---------------------------------------------------
def test_frame_is_hidden_until_a_region_exists(frame):
    assert not frame.is_visible()


def test_pieces_surround_the_region_on_all_four_sides(frame):
    frame.show_for(R, "16:9")
    rects = frame.piece_rects()
    assert frame.is_visible()
    assert rects["top"] == (R.x, R.y - frame.BAND, R.w, frame.BAND)
    assert rects["bottom"] == (R.x, R.y + R.h, R.w, frame.BAND)
    assert rects["left"] == (R.x - frame.BAND, R.y, frame.BAND, R.h)
    assert rects["right"] == (R.x + R.w, R.y, frame.BAND, R.h)


def test_no_piece_covers_any_pixel_of_the_recorded_area(frame):
    """R2/KTD2 by construction: the frame is rectangles that miss the region."""
    frame.show_for(R, "16:9")
    region = QRect(R.x, R.y, R.w, R.h)
    for role, rect in frame.piece_rects().items():
        if rect is None:
            continue
        box = QRect(*rect)
        assert not box.intersects(region), f"{role} overlaps the recorded area"


def test_no_piece_sits_over_the_region_so_clicks_reach_the_desktop(frame):
    """R3 by construction: no window exists where the user clicks to work."""
    frame.show_for(R, "16:9")
    centre = (R.x + R.w // 2, R.y + R.h // 2)
    on_edge = (R.x + R.w // 2, R.y)
    assert all(
        not _contains(rect, centre) for rect in frame.piece_rects().values() if rect)
    assert all(
        not _contains(rect, on_edge) for rect in frame.piece_rects().values() if rect)
    assert _contains(frame.piece_rects()["top"], (R.x + R.w // 2, R.y - 1))


def _contains(rect, point):
    if rect is None:
        return False
    x, y, w, h = rect
    return x <= point[0] < x + w and y <= point[1] < y + h


def test_pieces_paint_only_their_own_band(frame):
    # Rendering proof that does not depend on who happens to own the X stack:
    # render each piece into an image and check the pixels it produces.
    frame.show_for(R, "16:9")
    top = frame._pieces["top"].grab().toImage()
    assert (top.width(), top.height()) == (R.w, frame.BAND)
    idle = QColor(frame.IDLE_COLOR)
    painted = top.pixelColor(R.w // 2, 0)
    assert abs(painted.red() - idle.red()) < 40 and abs(painted.blue() - idle.blue()) < 40, (
        f"strip painted {painted.name()}, expected the idle colour {idle.name()}")
    frame.set_locked(True)
    rec = frame._pieces["top"].grab().toImage().pixelColor(R.w // 2, 0)
    assert QColor(rec).lightness() < QColor(painted).lightness(), "recording colour differs"


def test_tab_widens_to_fit_the_label_and_lives_above_the_region(frame):
    frame.show_for(R, "16:9")
    tab = frame.piece_rects()["tab"]
    assert tab is not None
    assert tab[3] >= frame.tab_height() > 0
    assert tab[0] + tab[2] >= min(frame.TAB_MIN_WIDTH, R.w)
    assert tab[1] + tab[3] <= R.y, "the tab sits outside the recorded area"


def test_a_flush_screen_edge_drops_that_side_instead_of_covering_the_region(frame):
    flush = Region(0, 0, 1280, 720)
    frame.show_for(flush, "16:9")
    rects = frame.piece_rects()
    region = QRect(flush.x, flush.y, flush.w, flush.h)
    for role, rect in rects.items():
        if rect is None:
            continue
        assert not QRect(*rect).intersects(region), role
    # the two flush sides fall off-screen entirely rather than overlapping
    for role in ("left", "top"):
        if rects[role] is not None:
            assert QRect(*rects[role]).intersected(region).isEmpty(), role


def test_clear_region_hides_the_frame(frame):
    frame.show_for(R, "16:9")
    assert frame.is_visible()
    frame.clear()
    assert not frame.is_visible()


def test_locked_frame_shows_the_recording_style_but_still_forwards(frame):
    frame.show_for(R, "16:9")
    frame.set_locked(True)
    assert frame._locked is True
    frame.begin_drag(R.x + R.w, R.y + R.h)   # grab the bottom-right corner
    frame.update_drag(R.x + R.w + 200, R.y + R.h + 200)
    settled = frame.end_drag(R.x + R.w + 200, R.y + R.h + 200)
    assert settled is not None and settled != R, (
        "a locked frame must not swallow the edit - the controller decides (KTD4)")


def test_drag_on_the_band_is_forwarded_as_a_settled_region(frame):
    frame.show_for(R, "16:9")
    frame.begin_drag(R.x + R.w // 2, R.y)     # middle of the top band
    frame.update_drag(R.x + R.w // 2 + 50, R.y + 40)
    assert frame.end_drag(R.x + R.w // 2 + 50, R.y + 40) == Region(450, 340, 640, 360)


def test_release_without_movement_is_not_forwarded(frame):
    frame.show_for(R, "16:9")
    frame.begin_drag(R.x + R.w // 2, R.y)
    assert frame.end_drag(R.x + R.w // 2, R.y) is None


# -- controller: single write gate ------------------------------------------
def test_update_region_emits_region_changed_without_changing_state(controller):
    controller.set_region(R)
    seen = []
    controller.region_changed.connect(lambda region: seen.append(region))
    moved = Region(500, 400, 640, 360)
    controller.update_region(moved)
    assert seen == [moved]
    assert controller.state is State.IDLE
    assert controller.region == moved


def test_set_region_and_update_region_share_the_recording_gate(controller):
    controller.set_region(R)
    controller.start_recording()
    blocked = []
    controller.region_edit_blocked.connect(lambda: blocked.append(1))
    assert controller.state is State.RECORDING
    controller.set_region(Region(0, 0, 320, 180))
    controller.update_region(Region(10, 10, 320, 180))
    assert controller.region == R, "neither entry point may move the region mid-recording"
    assert len(blocked) == 2


def test_region_edit_blocked_is_not_emitted_while_idle(controller):
    fired = []
    controller.region_edit_blocked.connect(lambda: fired.append(1))
    controller.update_region(R)
    assert fired == []


def test_selection_finished_writes_through_the_same_gate(controller):
    seen = []
    controller.region_changed.connect(lambda region: seen.append(region))
    controller.begin_selection()
    controller.selection_finished(R)
    assert seen == [R]
    assert controller.region == R
    assert controller.state is State.IDLE


def test_stop_then_edit_is_allowed_again(controller):
    controller.set_region(R)
    controller.start_recording()
    controller.stop_recording()
    controller.reset()
    moved = Region(600, 200, 640, 360)
    controller.update_region(moved)
    assert controller.region == moved
    controller.start_recording()           # the next take must use the dragged region
    assert controller.created["rec"].args[0] == moved


# -- main window wiring -----------------------------------------------------
class FakeRec:
    def __init__(self, region=None):
        self.region = region

    def start(self):
        pass

    def stop(self, *a, **k):
        pass

    @property
    def running(self):
        return True


def make_window():
    from app.mainwindow import MainWindow
    made = {}

    def make_recorder(region, aspect, out_path, with_audio, display=None):
        made["rec"] = FakeRec(region)
        return made["rec"]

    c = RecordingController(make_recorder=make_recorder,
                            audio_available=lambda: True,
                            make_path=lambda base_dir=None: "/tmp/sr_test.mp4")
    return MainWindow(c), c, made


def test_frame_is_hidden_while_the_modal_selector_is_open(qapp):
    win, c, _ = make_window()
    c.set_region(R)
    win._sync_frame()
    assert win._frame.is_visible()
    c.begin_selection()
    win._sync_frame()
    assert not win._frame.is_visible()
    c.selection_cancelled()
    win._sync_frame()
    assert win._frame.is_visible(), "cancelling the modal restores the original region"


def test_aspect_selector_is_disabled_during_recording(qapp):
    win, c, _ = make_window()
    c.set_region(R)
    c.start_recording()
    assert not win._aspect_box.isEnabled(), (
        "an aspect change mid-recording drops the region with no signal")
    c.stop_recording()
    c.reset()
    assert win._aspect_box.isEnabled()


def test_frame_tracks_region_changes_and_follows_the_controller(qapp):
    win, c, _ = make_window()
    c.set_region(R)
    win._sync_frame()
    assert win._frame.is_visible()
    moved = Region(900, 200, 640, 360)
    c.update_region(moved)
    assert win._frame.model.region == moved
    assert "900" in win._status.text()


def test_status_text_reports_the_edited_region_after_a_drag(qapp):
    win, c, _ = make_window()
    c.set_region(R)
    win._on_region_edited(Region(500, 400, 640, 360))
    assert "500" in win._status.text() and "640x360" in win._status.text()
    assert c.region == Region(500, 400, 640, 360)


def test_closing_the_main_window_takes_the_frame_with_it(qapp):
    win, c, _ = make_window()
    c.set_region(R)
    win._sync_frame()
    assert win._frame.is_visible()
    win.close()
    assert not win._frame.is_visible()
