"""Entry point: run preflight, then open the recorder window."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

from .preflight import describe, run_preflight


def _placeholder_window() -> QWidget:
    """Temporary window shown by the scaffold; replaced by MainWindow in U4."""
    win = QWidget()
    win.setWindowTitle("Screen Recorder")
    win.setFixedSize(460, 160)
    label = QLabel(
        "Screen Recorder\n\nEnvironment OK.\nControls land in the next unit.",
        win,
    )
    label.setAlignment(Qt.AlignCenter)
    return win


def main() -> int:
    app = QApplication(sys.argv)
    result = run_preflight()

    if not result.can_launch():
        QMessageBox.critical(None, "Cannot start", describe(result))
        return 1

    if not result.audio_monitor:
        QMessageBox.warning(
            None,
            "No system audio",
            "No system audio source found. Recordings will be silent unless "
            "audio is available when you press Record.\n\nContinue?",
        )

    window = _placeholder_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
