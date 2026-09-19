"""Full-screen translucent overlay for selecting an aspect-locked region (R1, R2, R3).

Drag to size the region, release to confirm, Esc / right-click to cancel.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QColor, QPainter, QPen, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

from .aspect import Region, snap_to_ratio


class RegionOverlay(QWidget):
    """Frameless, always-on-top, semi-transparent full-screen selector.

    Signals:
        region_selected(object): emits a Region when the user releases the drag.
        cancelled():            emitted on Esc or right-click.
    """

    region_selected = Signal(object)  # object => a Region dataclass
    cancelled = Signal()

    def __init__(self, aspect: str, parent=None):
        super().__init__(parent)
        self._aspect = aspect
        self._screen = None
        self._anchor = None
        self._region = None
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)

    def open(self) -> None:
        """Show the overlay covering the primary screen."""
        self._screen = QApplication.primaryScreen().geometry()
        self.setGeometry(self._screen)
        self.show()
        self.raise_()
        self.activateWindow()

    # -- input -----------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._anchor = event.globalPosition().toPoint()
            self._region = None
            self.update()
        elif event.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._anchor is None or self._screen is None:
            return
        cur = event.globalPosition().toPoint()
        g = self._screen
        self._region = snap_to_ratio(
            self._anchor.x(), self._anchor.y(),
            cur.x(), cur.y(),
            self._aspect, g.width(), g.height(),
        )
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._region is not None:
            self.region_selected.emit(self._region)
            self.close()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # -- rendering -------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        # Dim the whole screen.
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if self._region is not None:
            r = self._region
            rect = QRect(r.x, r.y, r.w, r.h)
            # Punch a see-through hole in the selected region.
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#4FC3F7"), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            painter.setPen(QPen(QColor("white")))
            painter.drawText(
                rect.adjusted(8, 0, -8, -24),
                Qt.AlignTop | Qt.AlignLeft,
                f"{r.w} x {r.h}  ({self._aspect})",
            )
        else:
            painter.setPen(QPen(QColor("white")))
            painter.drawText(
                self.rect().adjusted(16, 0, -16, -40),
                Qt.AlignBottom | Qt.AlignRight,
                f"Drag to select region ({self._aspect})  -  Esc to cancel",
            )
        painter.end()
