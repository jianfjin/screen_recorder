"""U1 (R2 / AE2): elapsed-time label on the main window while recording.

Runs offscreen; MainWindow is a plain QMainWindow (no translucent top-level),
so it can be constructed under QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

import pytest

from app.aspect import Region
from app.controller import RecordingController, State
from app.mainwindow import MainWindow


class FakeRecorder:
    def start(self):
        pass

    def stop(self):
        pass

    @property
    def running(self):
        return False


class FakeElapsed:
    def __init__(self, ms: int):
        self._ms = ms

    def start(self):
        pass

    def elapsed(self):
        return self._ms


def make_window():
    controller = RecordingController(
        make_recorder=lambda *a, **k: FakeRecorder(),
        audio_available=lambda: True,
        make_path=lambda base_dir=None: "/tmp/screen_test.mp4",
    )
    return MainWindow(controller), controller


def test_entering_recording_starts_timer_and_shows_zero(qapp):
    win, c = make_window()
    c.set_region(Region(0, 0, 640, 360))
    c.start_recording()
    assert c.state is State.RECORDING
    assert win._timer.isActive()
    assert win._time_label.text() == "00:00"
    c.stop_recording()


def test_tick_formats_elapsed_seconds(qapp):
    win, c = make_window()
    c.set_region(Region(0, 0, 640, 360))
    c.start_recording()
    win._elapsed = FakeElapsed(65_000)  # 65 s
    win._tick()
    assert win._time_label.text() == "01:05"
    c.stop_recording()


def test_leaving_recording_stops_timer_and_resets_label(qapp):
    win, c = make_window()
    c.set_region(Region(0, 0, 640, 360))
    c.start_recording()
    assert win._timer.isActive()
    c.stop_recording()
    assert not win._timer.isActive()
    assert win._time_label.text() == "00:00"
