import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.overlay import RegionOverlay


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _pt(x, y):
    return QPointF(float(x), float(y))


def _mouse(kind, x, y, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(
        kind, _pt(x, y), _pt(x, y), button, buttons, Qt.NoModifier
    )


def test_drag_produces_16_9_region(qapp):
    ov = RegionOverlay("16:9")
    ov.open()  # offscreen primary screen is 800x600
    results = []
    ov.region_selected.connect(results.append)
    ov.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 100, 100))
    ov.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, 700, 400, buttons=Qt.LeftButton)
    )
    ov.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, 700, 400, buttons=Qt.NoButton)
    )
    assert len(results) == 1
    r = results[0]
    # 600-wide drag snaps to 16:9 -> height derived as round(600*9/16)=338
    assert (r.x, r.y) == (100, 100)
    assert r.w == 600
    assert abs(r.w / r.h - 16 / 9) < 0.02
    ov.close()


def test_overlay_clamps_to_screen(qapp):
    ov = RegionOverlay("16:9")
    ov.open()
    results = []
    ov.region_selected.connect(results.append)
    ov.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 700, 550))
    ov.mouseMoveEvent(
        _mouse(QEvent.Type.MouseMove, 100, 100, buttons=Qt.LeftButton)
    )
    ov.mouseReleaseEvent(
        _mouse(QEvent.Type.MouseButtonRelease, 100, 100, buttons=Qt.NoButton)
    )
    assert len(results) == 1
    r = results[0]
    assert r.x >= 0 and r.y >= 0
    assert r.x + r.w <= 800 and r.y + r.h <= 600
    ov.close()


def test_escape_cancels(qapp):
    ov = RegionOverlay("16:9")
    ov.open()
    cancelled = []
    ov.cancelled.connect(lambda: cancelled.append(True))
    ov.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert cancelled == [True]
    ov.close()
