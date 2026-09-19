"""Main window: aspect choice, region selection, start/stop, status.

R2 (aspect choice), R6 (start/stop, single file, no pause), R8 (file path
shown after stop), F2 (no-audio prompt) live here.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .aspect import ASPECTS
from .controller import RecordingController, State
from .formatting import format_duration
from .overlay import RegionOverlay


class MainWindow(QMainWindow):
    def __init__(self, controller: RecordingController | None = None):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.setFixedSize(600, 190)

        self._overlay = None
        self._controller = controller or RecordingController.from_defaults(parent=self)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        top = QHBoxLayout()
        self._aspect_box = QComboBox()
        self._aspect_box.addItems(sorted(ASPECTS))
        self._aspect_box.currentTextChanged.connect(self._controller.set_aspect)
        top.addWidget(self._aspect_box)

        self._select_btn = QPushButton("Select Region")
        self._select_btn.clicked.connect(self._select_region)
        top.addWidget(self._select_btn)

        self._record_btn = QPushButton("Record")
        self._record_btn.setEnabled(False)
        self._record_btn.clicked.connect(self._controller.start_recording)
        top.addWidget(self._record_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._controller.stop_recording)
        top.addWidget(self._stop_btn)

        self._time_label = QLabel("00:00")
        time_font = QFont()
        time_font.setFamily("Monospace")
        time_font.setFixedPitch(True)
        self._time_label.setFont(time_font)
        self._time_label.setMinimumWidth(58)
        top.addWidget(self._time_label)

        top.addStretch(1)

        self._status = QLabel("Pick an aspect ratio, then select a region.")
        top.addWidget(self._status)
        root.addLayout(top)

        save_row = QHBoxLayout()
        save_row.addWidget(QLabel("Save to:"))
        self._save_dir_label = QLabel(str(self._default_save_dir()))
        save_row.addWidget(self._save_dir_label)
        save_row.addStretch(1)
        self._choose_btn = QPushButton("Choose…")
        self._choose_btn.clicked.connect(self._choose_save_dir)
        save_row.addWidget(self._choose_btn)
        root.addLayout(save_row)

        self._controller.state_changed.connect(self._on_state_changed)
        self._controller.region_ready.connect(self._on_region_ready)
        self._controller.region_invalidated.connect(self._on_region_invalidated)
        self._controller.audio_missing.connect(self._on_audio_missing)
        self._controller.recording_stopped.connect(self._on_stopped)
        self._controller.error.connect(self._on_error)

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _select_region(self):
        if self._overlay is not None and self._overlay.isVisible():
            return
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
            self._elapsed.start()
            self._time_label.setText(format_duration(0))
            self._timer.start()
            self._status.setText("Recording… press Stop when done.")
        elif state == State.SELECTING.value:
            self._status.setText("Drag to select the region; Esc cancels.")
        else:
            self._timer.stop()
            self._time_label.setText("00:00")

    def _tick(self) -> None:
        self._time_label.setText(format_duration(self._elapsed.elapsed() / 1000.0))

    def _default_save_dir(self) -> Path:
        return Path.home() / "Videos"

    def _choose_save_dir(self) -> None:
        current = self._controller.save_dir
        initial = str(current) if current else str(self._default_save_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Choose save directory", initial)
        if chosen:
            self._set_save_dir(chosen)

    def _set_save_dir(self, path: str) -> None:
        self._controller.set_save_dir(path if path else None)
        self._save_dir_label.setText(
            path if path else str(self._default_save_dir())
        )

    def _on_region_ready(self, region) -> None:
        self._record_btn.setEnabled(True)
        self._status.setText(
            f"Region {region.w}x{region.h} at ({region.x}, {region.y}) ready — press Record."
        )

    def _on_region_invalidated(self) -> None:
        self._record_btn.setEnabled(False)
        self._status.setText("Aspect changed — please select a region again.")

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
