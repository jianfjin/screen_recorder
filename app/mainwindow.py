"""Main window: aspect choice, region selection, start/stop, status.

R2 (aspect choice), R6 (start/stop, single file, no pause), R8 (file path
shown after stop), F2 (no-audio prompt) live here.

R1's seam lives here too: the buttons reach the controller through
`_start_recording` / `_stop_recording`, which is the only place the interface can
be moved out of the way before the grabber starts reading pixels (KTD1).

Note on the requirement numbers below: the legend above is this window's own
older numbering; the collapse, strip and restore hunks cite the recording-
control-strip plan, whose R6 is the strip beside the frame's bands and whose
R8 is the restore. Where a comment could read either way, it names the plan.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QPoint, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
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
from .frame import RegionFrame
from .overlay import RegionOverlay
from .strip import ControlStrip, should_collapse, strip_placement


class MainWindow(QMainWindow):
    def __init__(self, controller: RecordingController | None = None):
        super().__init__()
        self.setWindowTitle("Screen Recorder")
        self.setFixedSize(600, 190)

        self._overlay = None
        screen = QApplication.primaryScreen().geometry()
        self._frame = RegionFrame(screen.width(), screen.height())
        self._strip = ControlStrip()   # top-level like the frame: shown only while collapsed
        self._controller = controller or RecordingController.from_defaults(parent=self)

        # The collapse is state MainWindow owns, not the controller: where the
        # window was (`_restore_anchor`, a global `pos()`) and whether it is away.
        self._collapsed = False
        self._restore_anchor = None

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
        self._record_btn.clicked.connect(self._start_recording)
        top.addWidget(self._record_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_recording)
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
        self._controller.region_changed.connect(self._on_region_changed)
        self._controller.region_edit_blocked.connect(self._on_region_edit_blocked)
        self._frame.region_edited.connect(self._on_region_edited)
        self._strip.stop_requested.connect(self._stop_recording)
        self._controller.audio_missing.connect(self._on_audio_missing)
        self._controller.recording_stopped.connect(self._on_stopped)
        self._controller.error.connect(self._on_error)

        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # -- the recording seam (KTD1) ------------------------------------------
    def _start_recording(self) -> None:
        """Record, with this window off the desktop first if it is in the way.

        The collapse happens here rather than in `_on_state_changed` because
        `RecordingController._begin()` starts the grabber and only then announces
        RECORDING: driven from the state callback, the first few dozen
        milliseconds of this file would be this window (R1, KTD1) -- the same
        failure the frame's own bands hit last cycle.

        Whether it collapses at all is geometry, not guesswork: `frameGeometry()`
        because the decorated border is on the desktop and in the capture too
        (KTD4), recomputed now because the user may have dragged this window onto
        the region since the last take.
        """
        self._collapse_if_covering_region()
        self._controller.start_recording()
        if self._collapsed and self._controller.state is not State.RECORDING:
            # The interface moved for a capture that is not happening. Undo
            # it here, in the same call, whatever the reason the start returned
            # without recording -- the rollback hooked to error and audio_missing
            # covers the paths the controller announces, and this covers the
            # ones it does not. R9: never a desktop whose only control cannot
            # be used.
            self._restore_from_recording()

    def _stop_recording(self) -> None:
        """The one stop path (R10).

        Both buttons -- this window's and the strip's -- arrive here, and the
        controller's `stop_recording` stays the only close-out. Restoring the
        interface rides the state change it emits, not this call.
        """
        self._controller.stop_recording()

    def _collapse_if_covering_region(self) -> None:
        """The decision, in one place, for whoever is about to start capturing.

        Both callers need it: the Record button, and the no-audio prompt answered
        yes -- which resumes a start that already collapsed once and was rolled back
        to ask. R3 is the reason this is a question and not a habit: an interface
        that is not in the shot must never disappear from the desktop.
        """
        region = self._controller.region
        if region is not None and should_collapse(self.frameGeometry().getRect(), region):
            self._collapse_for_recording()

    def _collapse_for_recording(self) -> None:
        """Away with this window, up goes the strip, in that order. Idempotent.

        Called by `_start_recording`, and again by the no-audio prompt's answer
        (KTD1(a)) -- one body of collapse code, so a re-collapse cannot drift from
        the first one. Guarded by `_collapsed` because R5 fixes the strip's
        position at the moment it is computed: a second call must not move it.
        """
        if self._collapsed:
            return
        # The client corner, not pos(): pos() is the frame origin, and the
        # decoration a window manager puts around it is not part of what the
        # user was looking at (R8).
        self._restore_anchor = self.mapToGlobal(QPoint(0, 0))
        self.hide()
        screen = QApplication.primaryScreen().geometry()
        rect, _side, layout, inside = strip_placement(
            self._controller.region, screen.width(), screen.height())
        self._strip.place(rect, layout, inside)
        self._strip.set_stop_enabled(False)   # nothing is being captured yet (R9)
        self._strip.set_time(self._time_label.text())
        self._strip.show()                    # no gap with two interfaces missing
        self._strip.raise_()                  # KTD6: strip above the bands
        self._collapsed = True

    def _frame_extents(self) -> QPoint:
        """How far the decoration sets the client inside the frame it draws.

        Qt measures a window twice: pos() is the frame origin, the pixels the user
        recognises start at the client corner, and only the window manager knows
        the difference -- which it reports once the window is mapped.
        """
        return self.mapToGlobal(QPoint(0, 0)) - self.pos()

    def _restore_from_recording(self) -> None:
        """Put the window back on the pixels the user left it on (R8).

        The anchor is a client corner, not a pos(): pos() names the frame, and
        the decoration around it is for the window manager to decide. Showing a
        hidden window is the moment a manager may re-place it, so this aims once
        before the map and corrects after it. Offscreen the round trip is exact;
        the live row of the plan's Verification Contract is where a manager that
        changed its mind would show up -- and on this desktop, one did.
        """
        if not self._collapsed:
            return
        self._collapsed = False
        self._strip.hide()
        anchor, self._restore_anchor = self._restore_anchor, None
        if anchor is not None:
            self.move(anchor - self._frame_extents())
        self.show()
        if anchor is not None and self.mapToGlobal(QPoint(0, 0)) != anchor:
            # The manager changed the decoration while the window was hidden, and
            # that is the one case a restore trusting pos() gets a title bar wrong.
            self.move(anchor - self._frame_extents())

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
            self._show_time(format_duration(0))
            self._timer.start()
            self._status.setText("Recording… press Stop when done.")
            if self._collapsed:
                # The strip has been on the desktop since before the grabber
                # started; now there is finally something for it to stop (KTD1).
                self._strip.set_stop_enabled(True)
        else:
            if state == State.SELECTING.value:
                self._status.setText("Drag to select the region; Esc cancels.")
            else:
                self._timer.stop()
                self._show_time("00:00")
            # Leaving RECORDING is the authority for coming back, whichever way
            # it left; the helper is idempotent, so DONE and then IDLE is one
            # restore (R8).
            self._restore_from_recording()
        self._aspect_box.setEnabled(not recording)
        self._sync_frame()
        if recording and not self._collapsed:
            # The frame pieces are override-redirect; keep the controls above
            # them so a band crossing this window can never bury Record/Stop.
            # Collapsed, this window is off the desktop and the strip holds that
            # slot instead -- raising this one would bury the stop button (KTD6).
            self.raise_()

    def _tick(self) -> None:
        self._show_time(format_duration(self._elapsed.elapsed() / 1000.0))

    def _show_time(self, text: str) -> None:
        """KTD5: one timer and one clock in this window, shown in two places.

        The hidden window's label stays writable while collapsed, so the existing
        timer tests keep proving the same number without being re-pathed.
        """
        self._time_label.setText(text)
        self._strip.set_time(text)

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

    def _sync_frame(self) -> None:
        """Show, hide, or lock the frame from the controller's state (KTD5).

        Derived here and nowhere else, including on every state change, so a
        region the controller no longer holds can never leave a stale frame on
        the desktop.
        """
        recording = self._controller.state is State.RECORDING
        region = self._controller.region
        if region is None:
            self._frame.clear()
        elif self._controller.state is State.SELECTING:
            self._frame.clear()     # the modal selector draws the region
        else:
            self._frame.show_for(region, self._aspect_box.currentText())
            self._frame.set_locked(recording)
        if self._strip.is_visible():
            # KTD6: strip > bands > everything else, restacked from the one place
            # that lays the bands out, so a band can never end up covering the
            # only stop button that exists while the window is away (R6).
            self._strip.raise_()

    def _on_region_ready(self, region) -> None:
        self._record_btn.setEnabled(True)
        self._status.setText(self._region_summary(region))
        self._sync_frame()

    def _region_summary(self, region) -> str:
        return f"Region {region.w}x{region.h} at ({region.x}, {region.y}) ready — press Record."

    def _on_region_changed(self, region) -> None:
        self._sync_frame()
        self._status.setText(self._region_summary(region))

    def _on_region_edited(self, region) -> None:
        # A settled frame drag. The controller decides whether it lands.
        self._controller.update_region(region)

    def _on_region_edit_blocked(self) -> None:
        self._status.setText("Stop the recording before changing the region.")
        # The frame already moved its own pieces; snap them back onto the region
        # that is actually being captured (R8), without restacking windows.
        region = self._controller.region
        if region is not None:
            self._frame.sync_to(region, self._aspect_box.currentText())

    def _on_region_invalidated(self) -> None:
        self._record_btn.setEnabled(False)
        self._status.setText("Aspect changed — please select a region again.")
        self._frame.clear()

    def _on_audio_missing(self) -> None:
        # This signal fires synchronously from inside the `start_recording()`
        # call that `_start_recording` just made, so the window is already
        # hidden and the strip is up with a stop button that has nothing to
        # stop. Put both back before asking: the prompt's parent is the window
        # that is not on the desktop (R9, F4).
        self._restore_from_recording()
        answer = QMessageBox.question(
            self,
            "No system audio",
            "No system audio source is available. Continue with a silent "
            "recording?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            # Collapse again through the one seam, then continue silently.
            # Deliberately *not* `_start_recording()` or
            # `controller.start_recording()`: the probe that just failed would
            # run again and fail again, re-entering this handler without bound
            # (KTD1(a)).
            self._collapse_if_covering_region()
            self._controller.continue_without_audio()

    def _on_stopped(self, path: str) -> None:
        self._status.setText(f"Saved: {path}")
        self._controller.reset()
        self._record_btn.setEnabled(True)

    def closeEvent(self, event) -> None:
        # Both helpers are unparented top-levels, so both have to be put away by
        # hand. A strip still showing after this window closes leaves a process
        # with a visible window and no way to close it.
        self._collapsed = False
        self._restore_anchor = None
        # The strip is hidden rather than deleteLater'd, unlike the frame above it:
        # this window's attribute keeps exactly one reference to its C++ object and it
        # is still connected to the stop slot, so a delete here would only be safe
        # because nothing outlives it -- and there is nothing to gain.
        self._strip.hide()
        self._frame.clear()   # unparented top-level: hide it explicitly
        self._frame.deleteLater()
        super().closeEvent(event)

    def _on_error(self, message: str) -> None:
        # Restore first, for the same reason as the audio prompt: a failure on
        # the way in (`_begin` could not start the grabber) otherwise leaves a
        # desktop holding only a strip whose stop button is disabled, and a
        # warning parented to a hidden window (R9).
        self._restore_from_recording()
        self._status.setText(message)
        QMessageBox.warning(self, "Recording error", message)
