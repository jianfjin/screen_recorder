import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication

from app.aspect import Region
from app.controller import RecordingController, State


def _app():
    return QCoreApplication.instance() or QCoreApplication(["test"])


class FakeRecorder:
    def __init__(self, args):
        self.args = args
        self.started = False
        self.stop_calls = 0

    def start(self):
        self.started = True

    def stop(self, *a, **k):
        self.stop_calls += 1

    @property
    def running(self):
        return self.started and self.stop_calls == 0


def _make_controller(audio=True, fail_start=False):
    _app()
    created = {}

    def make_recorder(region, aspect, out_path, with_audio, display=None):
        if fail_start:
            raise RuntimeError("boom")
        rec = FakeRecorder((region, aspect, out_path, with_audio))
        created["rec"] = rec
        return rec

    calls = []
    controller = RecordingController(
        make_recorder=make_recorder,
        audio_available=lambda: audio,
        make_path=lambda: "/tmp/screen_test.mp4",
    )
    return controller, created, calls


def test_start_with_audio_enters_recording():
    c, created, _ = _make_controller(audio=True)
    c.set_region(Region(0, 0, 640, 360))
    c.start_recording()
    assert c.state is State.RECORDING
    assert created["rec"].started
    assert created["rec"].args[3] is True  # with_audio


def test_start_without_audio_emits_missing():
    c, created, _ = _make_controller(audio=False)
    c.set_region(Region(0, 0, 640, 360))
    events = []
    c.audio_missing.connect(lambda: events.append("missing"))
    c.start_recording()
    assert events == ["missing"]
    assert c.state is not State.RECORDING
    assert "rec" not in created


def test_continue_without_audio_starts_silent_recording():
    c, created, _ = _make_controller(audio=False)
    c.set_region(Region(0, 0, 640, 360))
    c.continue_without_audio()
    assert c.state is State.RECORDING
    assert created["rec"].args[3] is False  # with_audio False


def test_cancel_keeps_idle():
    c, _, _ = _make_controller(audio=False)
    assert c.begin_selection() is True
    assert c.state is State.SELECTING
    c.selection_cancelled()
    assert c.state is State.IDLE


def test_stop_emits_path_and_finalizes():
    c, created, _ = _make_controller(audio=True)
    c.set_region(Region(0, 0, 640, 360))
    stopped = []
    c.recording_stopped.connect(stopped.append)
    c.start_recording()
    c.stop_recording()
    assert created["rec"].stop_calls == 1
    assert stopped == ["/tmp/screen_test.mp4"]
    assert c.state is State.DONE


def test_start_without_region_reports_error():
    c, created, _ = _make_controller(audio=True)
    errors = []
    c.error.connect(errors.append)
    c.start_recording()
    assert len(errors) == 1 and "region" in errors[0].lower()
    assert "rec" not in created


def test_start_failure_does_not_enter_recording():
    c, created, _ = _make_controller(audio=True, fail_start=True)
    c.set_region(Region(0, 0, 640, 360))
    errors = []
    c.error.connect(errors.append)
    c.start_recording()
    assert c.state is State.IDLE
    assert errors and "boom" in errors[0]


def test_aspect_change_invalidates_region():
    c, _, _ = _make_controller(audio=True)
    invalidated = []
    c.region_invalidated.connect(lambda: invalidated.append(1))
    c.set_region(Region(0, 0, 640, 360))
    c.set_aspect("3:2")
    assert c._region is None
    assert invalidated == [1]
    # switching to the same aspect is a no-op; a fresh region sticks
    c.set_region(Region(0, 0, 640, 360))
    c.set_aspect("3:2")
    assert c._region is not None
    assert invalidated == [1]


def test_from_defaults_builds_idle_controller():
    _app()
    c = RecordingController.from_defaults()
    assert c.state is State.IDLE
    assert c._aspect == "16:9"
