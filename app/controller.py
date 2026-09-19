"""Recording state machine wiring the overlay, encoder, and output path.

States: IDLE -> SELECTING -> RECORDING -> DONE (and back to IDLE).
No pause/resume (R6). One start->stop cycle produces exactly one file (R8).
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal


class State(str, Enum):
    IDLE = "idle"
    SELECTING = "selecting"
    RECORDING = "recording"
    DONE = "done"


class RecordingController(QObject):
    """Thin state machine around the recorder.

    `make_recorder(region, aspect, out_path, with_audio, display)` returns an
    object with .start() / .stop() / .running — injectable for tests.
    `audio_available()` probes the system monitor source (KTD4 / F2).
    """

    state_changed = Signal(str)
    region_ready = Signal(object)
    audio_missing = Signal()
    recording_stopped = Signal(str)
    error = Signal(str)

    def __init__(self, make_recorder, audio_available, make_path, parent=None):
        super().__init__(parent)
        self._make_recorder = make_recorder
        self._audio_available = audio_available
        self._make_path = make_path
        self._state = State.IDLE
        self._region = None
        self._aspect = "16:9"
        self._recorder = None
        self._out_path = None

    @property
    def state(self) -> State:
        return self._state

    def set_aspect(self, aspect: str) -> None:
        self._aspect = aspect

    def set_region(self, region) -> None:
        self._region = region

    def _set_state(self, state: State) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state.value)

    def begin_selection(self) -> bool:
        """Return True if the UI should now show the selection overlay."""
        if self._state == State.RECORDING:
            return False
        self._set_state(State.SELECTING)
        return True

    def selection_cancelled(self) -> None:
        if self._state == State.SELECTING:
            self._set_state(State.IDLE)

    def selection_finished(self, region) -> None:
        self._region = region
        self._set_state(State.IDLE)
        self.region_ready.emit(region)

    def start_recording(self) -> None:
        if self._state == State.RECORDING:
            return
        if self._region is None:
            self.error.emit("Select a region before recording.")
            return
        if not self._audio_available():
            # F2: no usable monitor source; let the UI offer silent/cancel.
            self.audio_missing.emit()
            return
        self._begin(with_audio=True)

    def continue_without_audio(self) -> None:
        """F2 follow-up: proceed with the audio-less encoder variant."""
        if self._region is not None:
            self._begin(with_audio=False)

    def _begin(self, with_audio: bool) -> None:
        try:
            self._out_path = self._make_path()
            recorder = self._make_recorder(
                self._region, self._aspect, self._out_path, with_audio
            )
            recorder.start()
        except Exception as exc:  # surface, don't crash the GUI
            self.error.emit(f"Failed to start recording: {exc}")
            return
        self._recorder = recorder
        self._set_state(State.RECORDING)

    def stop_recording(self) -> None:
        if self._state != State.RECORDING or self._recorder is None:
            return
        recorder = self._recorder
        self._recorder = None
        path = self._out_path
        try:
            recorder.stop()
        finally:
            self._set_state(State.DONE)
            self.recording_stopped.emit(str(path))

    def reset(self) -> None:
        """Return to IDLE without dropping the selected region (R6: no resume)."""
        self._set_state(State.IDLE)
