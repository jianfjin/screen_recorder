"""Region selection for an aspect-locked capture area (R1, R2, R3).

Split into two layers so the drag logic is testable without a live display:
  * SelectionModel - pure two-phase state machine:
      1. drag: press -> move -> release produces a *provisional* region that
         stays visible on the overlay (it is not emitted yet);
      2. confirm: a click (or Enter/Space) confirms the provisional region,
         which is then emitted as region_selected. A new drag replaces the
         provisional region; Esc / right-click cancels everything.
  * RegionOverlay  - thin full-screen Qt widget that forwards mouse/keyboard
    events to the model and paints the selection (dimmed background, bright
    region border, size label, and a hint line while waiting for confirm).
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .aspect import Region, snap_to_ratio


class SelectionModel:
    """Pure two-phase drag-to-select state machine, anchored at the press point.

    Phase 1 (drag): press -> move -> release produces a provisional region
    that remains visible so the user can verify the pick.
    Phase 2 (confirm): a click (small displacement) or confirm() (Enter/Space)
    returns the provisional region with confirmed=True; a new drag replaces
    the provisional region; cancel() clears it.

    Holds no Qt types so it is trivially unit-testable.
    """

    # Press/release displacement below this (px) counts as a click, i.e. a
    # confirmation of the current provisional region rather than a new drag.
    CONFIRM_CLICK_THRESHOLD = 4

    def __init__(self, aspect: str, screen_w: int, screen_h: int):
        self._aspect = aspect
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._anchor: Optional[tuple] = None
        self._press: Optional[tuple] = None
        self._region: Optional[Region] = None
        self._provisional: Optional[Region] = None

    def set_aspect(self, aspect: str) -> None:
        self._aspect = aspect

    @property
    def region(self) -> Optional[Region]:
        """Region to display: the live drag while dragging, else the provisional."""
        return self._region or self._provisional

    @property
    def provisional(self) -> Optional[Region]:
        return self._provisional

    @property
    def dragging(self) -> bool:
        return self._anchor is not None

    def press(self, x: int, y: int) -> None:
        self._anchor = (x, y)
        self._press = (x, y)
        self._region = None

    def move(self, x: int, y: int) -> None:
        if self._anchor is None:
            return
        ax, ay = self._anchor
        self._region = snap_to_ratio(
            ax, ay, x, y, self._aspect, self._screen_w, self._screen_h
        )

    def release(self, x: int, y: int) -> Tuple[Optional[Region], bool]:
        """End the press. Returns (region, confirmed).

        Real drag (displacement >= CONFIRM_CLICK_THRESHOLD): sets a new
        provisional region and returns it with confirmed=False.
        Click with a pending provisional: returns (provisional, True).
        Click with no provisional, or a release with no press: (None, False).
        """
        if self._anchor is None:
            return (None, False)
        px, py = self._press
        moved = math.hypot(x - px, y - py) >= self.CONFIRM_CLICK_THRESHOLD
        self._anchor = None
        live = self._region
        self._region = None
        self._press = None
        if moved and live is not None:
            self._provisional = live
            return (live, False)
        if not moved and self._provisional is not None:
            return (self._provisional, True)
        return (None, False)

    def confirm(self) -> Optional[Region]:
        """Return the provisional region for keyboard confirmation."""
        return self._provisional

    def cancel(self) -> None:
        self._anchor = None
        self._press = None
        self._region = None
        self._provisional = None


class RegionOverlay(QWidget):
    """Frameless, always-on-top, semi-transparent full-screen selector.

    Signals:
        region_selected(object): a Region, when the user confirms the
            provisional selection (click or Enter/Space after a drag).
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
            p = event.globalPosition().toPoint()
            region, confirmed = self._model.release(p.x(), p.y())
            if confirmed and region is not None:
                self.region_selected.emit(region)
                self.close()
            else:
                # Provisional region (or nothing) — keep the overlay up so the
                # user can see what was selected and confirm/re-drag/cancel.
                self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._cancel()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self._model is not None:
                region = self._model.confirm()
                if region is not None:
                    self.region_selected.emit(region)
                    self.close()
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
        dragging = bool(self._model and self._model.dragging)
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
            if not dragging:
                # Provisional state: tell the user how to confirm.
                painter.drawText(
                    self.rect().adjusted(16, 0, -16, -40),
                    Qt.AlignBottom | Qt.AlignRight,
                    "Click or press Enter to confirm  ·  drag to re-select  ·  Esc to cancel",
                )
        else:
            painter.setPen(QPen(QColor("white")))
            painter.drawText(
                self.rect().adjusted(16, 0, -16, -40),
                Qt.AlignBottom | Qt.AlignRight,
                f"Drag to select region ({self._aspect})  -  Esc to cancel",
            )
        painter.end()
