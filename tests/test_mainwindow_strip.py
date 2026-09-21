"""U2 (R1, R4, R6, R7, R8, R10): the strip window, and the seam that hides the UI.

What is proved here is *wiring*: the window is off the desktop before the grabber
starts, the strip lands on the rectangle U1's geometry picked and nowhere else,
one clock drives both time labels, one stop path has two entrances, and every way
out of the collapse (stop, error, close) takes the strip with it.

U3 (R5, R9) added the rollback and coexistence cases at the bottom: a recording
that never started leaves no strip behind, and the strip neither moves under a
refused drag nor covers a frame band.

What cannot be proved offscreen, and is therefore the live/manual rows of the
plan's Verification Contract rather than an assertion:
  * stacking order -- Qt has `raise_()` but no way to read the X stack, so the
    tests spy on who gets raised last (KTD6) instead of looking it up;
  * focus stealing -- `QApplication.activeWindow()` is None offscreen whatever
    happens, so the tests assert the `WA_ShowWithoutActivating` attribute that is
    the mechanism, not the absence of a side effect (R7 / AE7);
  * whether the strip's pixels are actually in the capture -- that is U4's
    frame-reading check.

Fixture rule (plan U2 step 0): every collapse case here `show()`s the window and
lets the event loop settle first. A top-level that was never shown reports
`isVisible() is False` for reasons of its own, so bare visibility would let the
collapse assertions pass while nothing happened; they are anchored on
`win._collapsed` and on the saved anchor position instead.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app import strip as strip_model
from app.aspect import Region
from app.controller import RecordingController, State
from app.mainwindow import MainWindow
from app.strip import (
    BACKGROUND_COLOR,
    BAR,
    BAR_SIZE,
    LABEL_SIZE,
    STACKED,
    STACKED_SIZE,
    STRIP_GAP,
    STRIP_INSET,
    TEXT_COLOR,
    ControlStrip,
    strip_placement,
)

SCREEN = QApplication.primaryScreen().geometry()
SCREEN_W, SCREEN_H = SCREEN.width(), SCREEN.height()

# A region with a free band above it, so the strip has somewhere to go that the
# geometry does not have to fall back from.
REGION = Region(40, 120, 640, 360)
OVER_REGION = (60, 200)     # 604x194 of window, on top of region pixels
CLEAR_OF_REGION = (0, 560)  # the same window, entirely below the region


def watch_seam(rig):
    """Shadow every call the collapse touches, so the log is a call order.

    R1 is a claim about *when* the window goes away, not about where it ends up:
    a final-state check passes just as happily if the collapse happened after the
    grabber started and the first frames were already written.
    """
    def spy(label, real):
        def call(*args, **kwargs):
            rig.log.append(label)
            return real(*args, **kwargs)
        return call

    win = rig.win
    win.hide = spy("window.hide", win.hide)
    win.raise_ = spy("window.raise_", win.raise_)
    win._strip.place = spy("strip.place", win._strip.place)
    win._strip.show = spy("strip.show", win._strip.show)
    win._strip.raise_ = spy("strip.raise_", win._strip.raise_)
    controller_start = win._controller.start_recording
    win._controller.start_recording = spy("controller.start_recording", controller_start)
    return rig


class SpyRecorder:
    """The capture process, reduced to what the seam can be blamed for.

    `start()` is the instant x11grab begins reading those pixels, so it is the
    only honest place to ask what was on the desktop when recording began.
    """

    def __init__(self, observe, log, with_audio=None):
        self._observe = observe
        self.log = log
        self.desktop_at_start = None
        self.with_audio = with_audio   # which encoder variant the caller chose

    def start(self):
        self.desktop_at_start = self._observe()
        self.log.append("recorder.start")

    def stop(self, *args, **kwargs):
        self.log.append("recorder.stop")

    @property
    def running(self):
        return True


class Rig:
    """MainWindow + a real controller + a capture process that only takes notes."""

    def __init__(self, region=REGION, *, audio_available=None, recorder_factory=None):
        self.log = []
        self._recorder = None
        self._recorder_factory = recorder_factory
        self.probe_calls = 0
        probe = (lambda: True) if audio_available is None else audio_available

        def counted_probe():
            self.probe_calls += 1
            return probe()

        self.controller = RecordingController(
            make_recorder=self._make_recorder,
            audio_available=counted_probe,
            make_path=lambda base_dir=None: "/tmp/sr_strip.mp4",
        )
        self.win = MainWindow(self.controller)
        self.controller.set_region(region)

    def _make_recorder(self, region, aspect, out_path, with_audio, display=None):
        if self._recorder_factory is not None:
            return self._recorder_factory(self, region, aspect, out_path, with_audio)
        self._recorder = SpyRecorder(self.desktop, self.log, with_audio)
        return self._recorder

    @property
    def recorder(self):
        return self._recorder

    def desktop(self):
        """The observable R1, R9 and KTD1(b) are all actually about."""
        strip = self.win._strip
        return {
            "window": self.win.isVisible(),
            "collapsed": self.win._collapsed,
            "strip": strip.is_visible(),
            "stop_enabled": strip._stop_btn.isEnabled(),
        }

    def raised_windows(self, order):
        """Shadow `raise_()` on every window this rig owns, logging by name."""
        def spy(label, real):
            def call(*args, **kwargs):
                order.append(label)
                return real(*args, **kwargs)
            return call

        for role, piece in self.win._frame._pieces.items():
            piece.raise_ = spy(f"band:{role}", piece.raise_)
        self.win._strip.raise_ = spy("strip", self.win._strip.raise_)
        self.win.raise_ = spy("window", self.win.raise_)
        return order


@pytest.fixture
def window(qapp):
    opened = []

    def open_window(*, region=REGION, at=OVER_REGION, show=True, **rig_kwargs):
        rig = Rig(region=region, **rig_kwargs)
        opened.append(rig)
        if show:
            rig.win.show()
            assert QTest.qWaitForWindowExposed(rig.win), (
                "the offscreen platform never exposed the main window")
            qapp.processEvents()
            rig.win.move(*at)
            qapp.processEvents()
            assert rig.win.pos() == QPoint(*at), "the platform moved the window elsewhere"
        return rig

    yield open_window

    # Nothing visible may survive a test. The strip and the frame's bands are
    # unparented top-levels, so hiding the main window alone would not do it.
    for rig in opened:
        rig.win._strip.hide()
        for piece in rig.win._frame._pieces.values():
            piece.hide()
        rig.win.hide()


# -- R1: the window is gone before the pixels start being read ---------------
def test_recording_from_on_top_of_the_region_collapses_the_window(window):
    """Covers AE1 (offscreen half) and R1: hidden window, visible strip, recording."""
    rig = window()
    assert strip_model.should_collapse(
        rig.win.frameGeometry().getRect(), rig.controller.region) is True
    assert rig.win.isVisible() is True          # premise: it really was on screen

    rig.win._start_recording()

    assert rig.win._collapsed is True
    assert rig.win.isVisible() is False
    assert rig.win._strip.is_visible() is True
    assert rig.controller.state is State.RECORDING
    assert "recorder.start" in rig.log


def test_the_collapse_happens_before_the_controller_is_asked_to_start(window):
    """Covers R1 / KTD1: the order itself, not the resulting state.

    `_begin()` calls `recorder.start()` and only then announces RECORDING, so a
    collapse driven by `state_changed` would open the file with a few dozen
    milliseconds of this window in it.
    """
    rig = watch_seam(window(at=(200, 260)))

    rig.win._start_recording()

    assert rig.log == [
        "window.hide", "strip.place", "strip.show", "strip.raise_",
        "controller.start_recording", "recorder.start",
        # KTD6: the state change syncs the frame, and the strip goes back on top.
        "strip.raise_",
    ]
    assert rig.recorder.desktop_at_start == {
        "window": False, "collapsed": True, "strip": True, "stop_enabled": False,
    }, "what the grabber saw at frame one"


# -- R3 / AE6: an interface that is not in the way is not touched ------------
def test_a_window_clear_of_the_region_is_left_exactly_as_it_is(window):
    """Covers R3 / AE6 (F2): no collapse, no strip, business as usual.

    The position is chosen to genuinely miss the region: this suite's habitual
    default of (0, 0) with Region(0, 0, 640, 360) *does* intersect it, and pairing
    those here would measure the collapse instead of its absence.
    """
    rig = watch_seam(window(at=CLEAR_OF_REGION))
    assert strip_model.should_collapse(
        rig.win.frameGeometry().getRect(), rig.controller.region) is False, (
        "premise: this window really is clear of the region")

    rig.win._start_recording()

    assert rig.controller.state is State.RECORDING
    assert rig.win._collapsed is False
    assert rig.win.isVisible() is True
    assert rig.win._strip.is_visible() is False
    assert rig.recorder.desktop_at_start == {
        "window": True, "collapsed": False, "strip": False, "stop_enabled": False,
    }
    # Nothing in the collapse seam ran, and the window still raises itself the way
    # it always did when it is the thing the user is looking at.
    assert [entry for entry in rig.log if entry.startswith("strip.")] == []
    assert rig.log == ["controller.start_recording", "recorder.start", "window.raise_"]


# -- R8: coming back --------------------------------------------------------
def test_stopping_returns_the_window_to_the_spot_it_was_hidden_from(window):
    """Covers R8 / F1: the same pixels on screen again, strip gone.

    Measured at the client corner, because that is what the user was looking at.
    `pos()` is the frame origin and the decoration above it is a window manager
    matter: on a live session those extents are only reported once the window is
    mapped, so a window coming back from hidden can match on `pos()` and still
    land its pixels a title bar lower (the live row of R8 caught exactly that).
    """
    rig = window()
    before = rig.win.mapToGlobal(QPoint(0, 0))

    rig.win._start_recording()
    assert rig.win._restore_anchor == before, "the collapse saved the wrong anchor"

    rig.win._stop_recording()

    assert rig.win._collapsed is False
    assert rig.win.isVisible() is True
    assert rig.win.mapToGlobal(QPoint(0, 0)) == before
    assert rig.win.pos() == QPoint(*OVER_REGION)
    assert rig.win._strip.is_visible() is False
    # `stop_recording` passes through DONE (the restore rode that change) and
    # `_on_stopped` resets to IDLE, which is the state a stopped recorder is in.
    assert rig.controller.state is State.IDLE
    # R8's deadline: the restore rode the state change, which precedes the path.
    assert "Saved:" in rig.win._status.text()


def test_restoring_is_idempotent(window):
    """Every way out of the collapse calls one helper; twice is not twice.

    Leaving RECORDING emits DONE and then, after `reset()`, IDLE -- a restore that
    was not idempotent would move the window twice and race the WM over it.
    """
    rig = window()
    rig.win._start_recording()

    rig.win._restore_from_recording()
    anchor_after_first = rig.win.pos()
    rig.win._restore_from_recording()          # already back: must change nothing
    rig.controller.reset()                     # the IDLE transition does it again

    assert rig.win.isVisible() is True
    assert rig.win.pos() == anchor_after_first
    assert rig.win._collapsed is False
    assert rig.win._strip.is_visible() is False
    assert rig.win._restore_anchor is None


def test_closing_the_main_window_takes_the_strip_with_it(window):
    """A strip left on the desktop would keep the process alive after closing.

    Mirrors `test_closing_the_main_window_takes_the_frame_with_it`.
    """
    rig = window()
    rig.win._start_recording()
    assert rig.win._strip.is_visible() is True

    rig.win.close()

    assert rig.win._strip.is_visible() is False
    assert rig.win._frame.is_visible() is False


# -- R4 / KTD5: one clock, two displays --------------------------------------
class FakeElapsed:
    def __init__(self, ms):
        self._ms = ms

    def start(self):
        pass

    def elapsed(self):
        return self._ms


def test_the_strip_and_the_window_always_show_the_same_time(window):
    """Covers R4 / KTD5: same text, same format, one timer between them."""
    rig = window()
    rig.win._start_recording()
    assert rig.win._time_label.text() == rig.win._strip._time_label.text() == "00:00"

    for ms, expected in ((0, "00:00"), (65_000, "01:05"), (3_725_000, "01:02:05")):
        rig.win._elapsed = FakeElapsed(ms)
        rig.win._tick()
        assert rig.win._time_label.text() == expected
        assert rig.win._strip._time_label.text() == expected, (
            "the strip shows a different time than the window it replaced")

    # The clock stayed in MainWindow: the strip displays a number, it does not
    # keep one.
    assert rig.win._timer.parent() is rig.win
    assert rig.win._strip.findChildren(QTimer) == []


def test_the_strips_stop_waits_for_the_capture_to_be_running(window):
    """Covers KTD1(b) and R9's timing half: on the desktop before it is clickable.

    The strip has to exist the moment the window disappears -- the audio probe
    that follows is a synchronous call on the GUI thread, up to 6s -- but pressing
    Stop before anything is being captured has nothing to stop.
    """
    rig = window()
    rig.win._start_recording()

    assert rig.recorder.desktop_at_start["stop_enabled"] is False
    assert rig.win._strip._stop_btn.isEnabled() is True, "recording -> clickable"

    rig.win._stop_recording()
    rig.win._start_recording()                 # a second take, same promise
    assert rig.recorder.desktop_at_start["stop_enabled"] is False, (
        "a re-collapse must not inherit an enabled button")


# -- R10: one stop path, two entrances ---------------------------------------
def test_the_strips_stop_button_is_the_same_stop_as_the_windows(window):
    """Covers R10 / AE4: one recorder.stop() for either button."""
    rig = window()
    rig.win._start_recording()

    rig.win._strip._stop_btn.click()

    assert rig.log.count("recorder.stop") == 1
    assert rig.controller.state is State.IDLE
    assert rig.win.isVisible() is True
    assert rig.win._strip.is_visible() is False

    rig.win._stop_btn.click()                  # the window is back; the old way out
    assert rig.log.count("recorder.stop") == 1, "no second close-out path"


def test_the_strip_has_no_way_to_reach_the_controller(window):
    """Covers R10 structurally: the strip owns a signal, not a recorder (KTD2)."""
    rig = window()
    held = [value for value in vars(rig.win._strip).values()
            if isinstance(value, RecordingController)]

    assert held == []
    assert hasattr(rig.win._strip, "stop_requested")


# -- R7 / KTD2: the window recipe --------------------------------------------
def test_the_strip_is_the_same_kind_of_window_the_frame_uses(window):
    """Covers R7 structurally: frameless, on top, WM-bypassing, never activating.

    `WA_ShowWithoutActivating` is the mechanism behind "showing it disturbs
    nobody". That nobody is disturbed is the "焦点打扰" manual row, because
    `QApplication.activeWindow()` is None offscreen either way.
    """
    rig = window()
    strip = rig.win._strip
    flags = strip.windowFlags()

    assert strip.testAttribute(Qt.WA_ShowWithoutActivating) is True
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert flags & Qt.X11BypassWindowManagerHint
    assert strip.parentWidget() is None and strip.isWindow(), "a top-level, not a bar"


def test_the_strip_sits_exactly_on_the_rectangle_the_geometry_picked(window):
    """U1's proof only holds if the window goes where the model said (KTD3).

    Everything U1 exhausted over hundreds of regions is a claim about a rectangle;
    this is the one link that turns it into a claim about pixels.
    """
    rig = window()
    rect, side, layout, inside = strip_placement(REGION, SCREEN_W, SCREEN_H)

    rig.win._start_recording()

    assert rig.win._strip.geometry().getRect() == rect
    assert (rig.win._strip.width(), rig.win._strip.height()) == (rect[2], rect[3])
    assert inside is False and rig.win._strip.is_over_region is False
    for child in (rig.win._strip._time_label, rig.win._strip._stop_btn):
        global_box = QRect(child.mapToGlobal(QPoint(0, 0)), child.size())
        assert QRect(*rect).contains(global_box), (
            f"{child.objectName()} painted outside the strip's proved rectangle")


# -- R6 / KTD6: the stacking contract, as far as Qt lets it be seen ----------
def test_the_strip_is_the_last_window_raised_after_a_frame_sync(window):
    """Covers R6 structurally: strip > bands. Qt cannot read the X stack.

    That the stop button really is above everything, and that no band is buried,
    is the "遮挡与叠放" manual row plus U4's frame reading.
    """
    rig = window()
    rig.win._start_recording()
    order = rig.raised_windows([])

    rig.win._sync_frame()

    assert order[-1] == "strip", f"raised last: {order}"
    assert order[:-1] == [f"band:{role}" for role in rig.win._frame.ROLES], (
        f"the bands are laid out, then out-ranked: {order}")


def test_a_collapsed_window_does_not_raise_itself(window):
    """Covers KTD6: the raise that kept the buttons above the bands is pointless
    when there are no buttons on screen."""
    rig = watch_seam(window(at=(300, 340)))

    rig.win._start_recording()

    assert "window.raise_" not in rig.log
    assert rig.log.count("strip.raise_") >= 1


# -- the strip's own contents (R4) -------------------------------------------
def test_the_two_layouts_put_the_label_and_the_stop_button_where_the_constants_say(qapp):
    """The widget geometry that maps `strip_placement`'s rect onto real controls.

    bar (184x44): INSET 8 + label 88 + GAP 8 + button 72 + INSET 8 = 184, both
    centred in the 44 of height. stacked (104x74): both centred horizontally, the
    label at INSET and the button INSET+22+GAP below it -> 8+22+8+28+8 = 74.
    """
    strip = ControlStrip()
    try:
        assert (strip._time_label.text(), strip._stop_btn.text()) == ("00:00", "Stop")
        assert strip._stop_btn.isEnabled() is False, "no capture yet (R9)"

        strip.place((0, 0) + BAR_SIZE, BAR, False)
        assert (strip.width(), strip.height()) == BAR_SIZE
        assert strip._time_label.geometry().getRect() == (8, 11, 88, 22)
        assert strip._stop_btn.geometry().getRect() == (104, 8, 72, 28)

        strip.place((0, 0) + STACKED_SIZE, STACKED, False)
        assert (strip.width(), strip.height()) == STACKED_SIZE
        assert strip._time_label.geometry().getRect() == (8, 8, 88, 22)
        assert strip._stop_btn.geometry().getRect() == (16, 38, 72, 28)
    finally:
        strip.deleteLater()


def test_the_strip_paints_its_own_colours_not_the_desktops(qapp):
    """Covers KTD7: the two published colours are on the pixels, not inherited.

    Inheriting the palette here would paint Qt's window grey, which is near enough
    to the frame's white marks that a leaked strip would read as a leaked frame. So
    this checks the rendered output, not a comment about it.
    """
    strip = ControlStrip()
    try:
        assert QColor(strip.palette().color(QPalette.Window)).name().lower() != \
            BACKGROUND_COLOR.lower(), "premise: this is not a palette colour"
        strip.place((0, 0) + BAR_SIZE, BAR, False)
        image = strip.grab().toImage()

        # An inset pixel and one in the gap between the controls: strip background,
        # nowhere near either control.
        for x, y in ((2, 2), (STRIP_INSET + LABEL_SIZE[0] + STRIP_GAP // 2, 2)):
            assert QColor(image.pixel(x, y)).name().lower() == BACKGROUND_COLOR.lower(), (x, y)

        target = QColor(TEXT_COLOR)
        closest = min(
            max(abs(QColor(image.pixel(px, py)).red() - target.red()),
                abs(QColor(image.pixel(px, py)).green() - target.green()),
                abs(QColor(image.pixel(px, py)).blue() - target.blue()))
            for py in range(11, 33) for px in range(8, 96))
        assert closest <= 24, f"no glyph in TEXT_COLOR inside the label (closest {closest})"
    finally:
        strip.deleteLater()


def test_the_strip_knows_when_it_lands_inside_the_region(qapp):
    """Covers R2's edge: `inside` is readable off the window, not only the model."""
    strip = ControlStrip()
    try:
        strip.place((308, 0, 184, 44), BAR, True)
        assert strip.is_over_region is True
        strip.place((308, 0, 184, 44), BAR, False)
        assert strip.is_over_region is False
        assert strip.is_visible() is False, "placing is not showing"
    finally:
        strip.deleteLater()


# -- the seam is the seam ---------------------------------------------------
def test_starting_straight_through_the_controller_collapses_nothing(window):
    """Why the existing timer/frame tests pass untouched: nothing derives from state.

    KTD1 puts the collapse in the request seam on purpose. The old path --
    `controller.start_recording()` -- is how `tests/test_mainwindow_timer.py` and
    `tests/test_mainwindow_frame.py` start a recording, and it has to stay exactly
    as observable as it was, because those windows are never on the desktop.
    """
    rig = window()
    assert rig.win._collapsed is False

    rig.controller.start_recording()

    assert rig.controller.state is State.RECORDING
    assert rig.win._collapsed is False
    assert rig.win.isVisible() is True
    assert rig.win._strip.is_visible() is False

    rig.controller.stop_recording()


def test_the_record_button_goes_through_the_seam(window):
    """Covers R1's premise: Record has to reach MainWindow's slot, not the
    controller's (the Problem Frame's "no seam to insert anything into")."""
    rig = watch_seam(window(at=(120, 300)))
    # Record is enabled by `region_ready`, i.e. by an actual selection, which is
    # what a user clicking it would have done first.
    rig.controller.begin_selection()
    rig.controller.selection_finished(REGION)
    assert rig.log == [] and rig.win._record_btn.isEnabled()

    rig.win._record_btn.click()

    assert "window.hide" in rig.log, "Record still bypasses the seam"
    assert rig.log.index("window.hide") < rig.log.index("recorder.start")
    assert rig.win._collapsed is True
    assert rig.recorder.desktop_at_start["window"] is False

    rig.win._stop_btn.click()
    assert rig.win.isVisible() is True


# ==========================================================================
# U3 (R5, R9): the paths where the recording never started, and living beside
# the frame's bands.
# ==========================================================================
def test_the_audio_prompt_is_asked_of_a_window_the_user_can_see(window, monkeypatch):
    """Covers AE5 / F4 / R9: the rollback happens before the question, not after.

    `audio_missing` is emitted synchronously from inside the
    `controller.start_recording()` that `_start_recording` just called, so without
    the restore the dialog would be parented to a hidden window while the desktop
    held nothing but a strip whose stop button does nothing.
    """
    rig = window(audio_available=lambda: False)
    seen = {}

    def question(*args, **kwargs):
        seen["at_prompt"] = rig.desktop()
        return QMessageBox.No

    monkeypatch.setattr("app.mainwindow.QMessageBox.question", question)

    rig.win._start_recording()

    assert seen["at_prompt"] == {
        "window": True, "collapsed": False, "strip": False, "stop_enabled": False,
    }, "the prompt was asked of a desktop with nothing clickable on it"
    assert rig.controller.state is not State.RECORDING
    assert rig.recorder is None, "nothing was captured, so nothing may be running"
    assert rig.win.isVisible() is True and rig.win._strip.is_visible() is False


def test_answering_yes_recollapses_without_re_entering_the_seam(window, monkeypatch):
    """Covers R9 / KTD1(a): one more collapse, exactly one more look at the audio.

    Calling `_start_recording()` again from here would re-run the probe that just
    failed and raise the same prompt again, forever. Only the collapse repeats.
    """
    rig = window(audio_available=lambda: False)

    def question(*args, **kwargs):
        return QMessageBox.Yes

    monkeypatch.setattr("app.mainwindow.QMessageBox.question", question)

    rig.win._start_recording()

    assert rig.probe_calls == 1, f"the probe ran {rig.probe_calls} times: recursion"
    assert rig.recorder is not None and rig.recorder.with_audio is False
    assert rig.recorder.desktop_at_start == {
        "window": False, "collapsed": True, "strip": True, "stop_enabled": False,
    }, "a silent take must be as clean as one with sound"
    assert rig.controller.state is State.RECORDING
    assert rig.win._strip._stop_btn.isEnabled() is True, "now there is something to stop"


def test_a_grabber_that_will_not_start_leaves_no_strip_behind(window, monkeypatch):
    """Covers R9: `error` on the way in is a rollback, not an exception to it."""
    def boom(*args, **kwargs):
        raise RuntimeError("ffmpeg refused to start")

    rig = window(recorder_factory=boom)
    seen = {}

    def warning(*args, **kwargs):
        seen["at_warning"] = rig.desktop()

    monkeypatch.setattr("app.mainwindow.QMessageBox.warning", warning)

    rig.win._start_recording()

    assert seen["at_warning"] == {
        "window": True, "collapsed": False, "strip": False, "stop_enabled": False,
    }, "a failed start must not leave a live strip"
    assert "Failed to start recording" in rig.win._status.text()


def test_the_strip_does_not_move_when_a_drag_is_refused(window):
    """Covers R5: the placement is computed once, at the collapse (KTD3)."""
    rig = window()
    rig.win._start_recording()
    before = rig.win._strip.geometry().getRect()

    rig.controller.update_region(Region(1200, 400, 640, 360))   # refused mid-recording

    assert rig.controller.region == REGION
    assert rig.win._strip.geometry().getRect() == before, (
        "the strip followed a region that was never moved")


def test_the_strip_and_the_bands_cover_no_pixel_of_each_other(window):
    """Covers R6: geometry first, stacking second -- a raise cannot fix an overlap.

    Global rectangles only. `QWidget.rect()` on a top-level is always the local
    (0, 0, w, h), so intersecting with that would compare the strip's size to the
    bands and never notice where the strip actually is.
    """
    rig = window()
    rig.win._start_recording()
    strip_rect = QRect(*rig.win._strip.geometry().getRect())

    for role, piece in rig.win._frame._pieces.items():
        band = QRect(*piece.geometry().getRect())
        overlap = strip_rect.intersected(band)
        assert overlap.width() <= 0 or overlap.height() <= 0, (
            f"the strip sits on the {role} piece: {strip_rect} vs {band}")


def test_a_region_with_no_free_band_still_collapses_onto_an_inside_strip(window):
    """Covers AE3 at R2's boundary: full screen, so the strip is in the shot.

    The settled decision: collapse anyway. The strip is far smaller than the
    window it replaces, and a full-screen recording is not refused for it.
    """
    rig = window(region=Region(0, 0, SCREEN_W, SCREEN_H), at=(100, 100))

    rig.win._start_recording()

    assert rig.win._collapsed is True
    assert rig.win._strip.is_visible() is True
    assert rig.win._strip.is_over_region is True
    rect = rig.win._strip.geometry().getRect()
    assert rect[0] >= 0 and rect[1] >= 0
    assert QRect(0, 0, SCREEN_W, SCREEN_H).contains(QRect(*rect)), "off the screen"


def test_two_takes_place_the_strip_from_where_the_window_is_now(window):
    """Covers R3 and R8 as a pair, across takes, with nothing left cached.

    The window moves between takes, so a later take must not reuse the answer the
    first one computed -- nor the rectangle the first one left the strip in.
    """
    rig = window(at=OVER_REGION)

    rig.win._start_recording()
    first = rig.win._strip.geometry().getRect()
    assert rig.win._collapsed is True
    rig.win._stop_recording()
    assert rig.win._restore_anchor is None

    rig.win.move(*CLEAR_OF_REGION)
    rig.win._start_recording()
    assert rig.win._collapsed is False
    assert rig.win._strip.is_visible() is False
    rig.win._stop_recording()

    rig.win.move(*OVER_REGION)
    rig.win._start_recording()
    assert rig.win._collapsed is True
    assert rig.win._strip.geometry().getRect() == first, (
        "the same region must place the strip in the same spot")
