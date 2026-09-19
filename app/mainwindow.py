"""Main window: aspect choice, region selection, start/stop, status.

R2 (aspect choice), R6 (start/stop, single file, no pause), R8 (file path
shown after stop), F2 (no-audio prompt) live here.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QWidget,
)

from .aspect import ASPECTS
from .controller import RecordingController, State
from .encoder import Recorder, build_args, make_output_path
from .overlay import RegionOverlay
from .preflight import check_audio_monitor


class MainWindow(QMainWindow):
    def __init__(self, controller: RecordingController | None = None):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.setFixedSize(520, 140)

        self._overlay = None
        self._controller = controller or RecordingController(
            make_recorder=self._default_make_recorder,
            audio_available=check_audio_monitor,
            make_path=make_output_path,
            parent=self,
        )

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        self._aspect_box = QComboBox()
        self._aspect_box.addItems(sorted(ASPECTS))
        self._aspect_box.currentTextChanged.connect(self._controller.set_aspect)
        layout.addWidget(self._aspect_box)

        self._select_btn = QPushButton("Select Region")
        self._select_btn.clicked.connect(self._select_region)
        layout.addWidget(self._select_btn)

        self._record_btn = QPushButton("Record")
        self._record_btn.setEnabled(False)
        self._record_btn.clicked.connect(self._controller.start_recording)
        layout.addWidget(self._record_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._controller.stop_recording)
        layout.addWidget(self._stop_btn)

        layout.addStretch(1)

        self._status = QLabel("Pick an aspect ratio, then select a region.")
        layout.addWidget(self._status)

        self._controller.state_changed.connect(self._on_state_changed)
        self._controller.region_ready.connect(self._on_region_ready)
        self._controller.audio_missing.connect(self._on_audio_missing)
        self._controller.recording_stopped.connect(self._on_stopped)
        self._controller.error.connect(self._on_error)

    # -- wiring helpers ----------------------------------------------------
    def _default_make_recorder(self, region, aspect, out_path, with_audio):
        args = build_args(region, aspect, out_path, with_audio=with_audio)
        return Recorder(args)

    def _select_region(self):
        if not self._controller.begin_selection():
            return
        overlay = RegionOverlay(self._aspect_box.currentText())
        overlay.region_selected.connect(self._controller.selection_finished)
        overlay.cancelled.connect(self._controller.selection_cancelled)
        self._overlay = overlay
        overlay.open()

    def _on_state_changed(self, state: str) -> None:
        recording = state == State.RECORDING.value
        self._select_btn.setEnabled(not recording)
        self._record_btn.setEnabled(not recording)
        self._stop_btn.setEnabled(recording)
        if recording:
            self._status.setText("Recording… press Stop when done.")
        elif state == State.SELECTING.value:
            self._status.setText("Drag to select the region; Esc cancels.")

    def _on_region_ready(self, region) -> None:
        self._record_btn.setEnabled(True)
        self._status.setText(f"Region {region.w}x{region.h} ready — press Record.")

    def _on_audio_missing(self) -> None:
        answer = QMessageBox.question(
            self,
            "No system audio",
            "No system audio source is available. Continue with a silent "
            "recording?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self._controller.continue_without_audio()

    def _on_stopped(self, path: str) -> None:
        self._status.setText(f"Saved: {path}")
        self._controller.reset()
        self._record_btn.setEnabled(True)

    def _on_error(self, message: str) -> None:
        self._status.setText(message)
        QMessageBox.warning(self, "Recording error", message)
