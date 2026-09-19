"""Region selection for an aspect-locked capture area (R1, R2, R3).

Split into two layers so the drag logic is testable without a live display:
  * SelectionModel - pure state machine (anchor -> move -> release -> Region).
  * RegionOverlay  - thin full-screen Qt widget that forwards mouse events
    to the model and paints the selection.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .aspect import Region, snap_to_ratio


class SelectionModel:
    """Pure drag-to-select state machine, anchored at the press point.

    Emits a Region on release if a valid rectangle was produced; nothing on
    cancel or an empty drag. Holds no Qt types so it is trivially unit-testable.
    """

    def __init__(self, aspect: str, screen_w: int, screen_h: int):
        self._aspect = aspect
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._anchor: Optional[tuple] = None
        self._region: Optional[Region] = None

    def set_aspect(self, aspect: str) -> None:
        self._aspect = aspect

    @property
    def region(self) -> Optional[Region]:
        return self._region

    @property
    def dragging(self) -> bool:
        return self._anchor is not None

    def press(self, x: int, y: int) -> None:
        self._anchor = (x, y)
        self._region = None

    def move(self, x: int, y: int) -> None:
        if self._anchor is None:
            return
        ax, ay = self._anchor
        self._region = snap_to_ratio(
            ax, ay, x, y, self._aspect, self._screen_w, self._screen_h
        )

    def release(self) -> Optional[Region]:
        """End the drag. Returns the Region if valid, else None (and resets)."""
        region = self._region
        self._anchor = None
        self._region = None
        return region

    def cancel(self) -> None:
        self._anchor = None
        self._region = None


class RegionOverlay(QWidget):
    """Frameless, always-on-top, semi-transparent full-screen selector.

    Signals:
        region_selected(object): a Region, when the user releases a valid drag.
        cancelled():            on Esc or right-click.
    """

    region_selected = Signal(object)
    cancelled = Signal()

    def __init__(self, aspect: str, parent=None):
        super().__init__(parent)
        self._aspect = aspect
        self._screen = None
        self._model: Optional[SelectionModel] = None
        self.setFocusPolicy(Qt.StrongFocus)

    def open(self) -> None:
        """Cover the primary screen and start accepting the drag."""
        screen = QApplication.primaryScreen().geometry()
        self._screen = screen
        self._model = SelectionModel(self._aspect, screen.width(), screen.height())
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(screen)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    # -- input ------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            p = event.globalPosition().toPoint()
            self._model.press(p.x(), p.y())
            self.update()
        elif event.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, event) -> None:
        if self._model is None or not self._model.dragging:
            return
        p = event.globalPosition().toPoint()
        self._model.move(p.x(), p.y())
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._model is not None:
            region = self._model.release()
            if region is not None:
                self.region_selected.emit(region)
                self.close()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def _cancel(self) -> None:
        if self._model is not None:
            self._model.cancel()
        self.cancelled.emit()
        self.close()

    # -- rendering --------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        region = self._model.region if self._model else None
        if region is not None:
            rect = region.as_qrect()
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
                f"{region.w} x {region.h}  ({self._aspect})",
            )
        else:
            painter.setPen(QPen(QColor("white")))
            painter.drawText(
                self.rect().adjusted(16, 0, -16, -40),
                Qt.AlignBottom | Qt.AlignRight,
                f"Drag to select region ({self._aspect})  -  Esc to cancel",
            )
        painter.end()
