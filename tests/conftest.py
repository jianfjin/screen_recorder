"""Shared pytest fixtures for the screen recorder test suite.

Qt permits exactly one application object per process. The controller tests
only need a QCoreApplication, while the MainWindow tests need a QApplication;
creating both in one process aborts. We create a single shared QApplication
(offscreen) up front and reuse it everywhere, so the two coexist cleanly.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

_qapp = QApplication.instance() or QApplication(["screen-recorder-tests"])


@pytest.fixture(scope="session")
def qapp():
    """The single shared offscreen QApplication for the whole suite."""
    return _qapp
