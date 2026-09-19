"""Entry point: preflight gate, then the recorder window."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from .controller import RecordingController
from .mainwindow import MainWindow
from .preflight import describe, run_preflight


def main() -> int:
    app = QApplication(sys.argv)
    result = run_preflight()

    if not result.can_launch():
        QMessageBox.critical(None, "Cannot start", describe(result))
        return 1

    controller = RecordingController.from_defaults()
    window = MainWindow(controller)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
