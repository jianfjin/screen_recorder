"""Persistent, draggable frame around the selected capture region (R1-R8).

Two layers, mirroring `app/overlay.py`:
  * RegionFrameModel - pure edit-the-existing-region state machine. Grab the
    border band to move the whole frame; grab a corner handle to rescale it
    under the locked aspect. It never decides whether an edit is *allowed*:
    editing is the controller's call (KTD4), so a locked frame still computes
    geometry and the controller refuses the write.
  * RegionFrame - a thin always-on-top ring window. Its mask is the frame rect
    minus the region, so the hollow centre passes clicks through to whatever is
    underneath and only the band receives presses (KTD1). Nothing is ever
    painted inside the region, which is what keeps the frame out of the
    recording (KTD2).
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QRegion
from PySide6.QtWidgets import QWidget

from .aspect import Region, move_region, resize_region_to_ratio

MOVE = "move"
RESIZE = "resize"

Corner = str
Mode = Tuple[str, Optional[Corner]]


class RegionFrameModel:
    """Pure geometry of dragging an existing region: move it, or rescale it.

    A press resolves to one mode up front: within `CORNER_GRAB_PX` of a corner
    it resizes from the opposite corner as anchor, anywhere else on the band it
    moves. `move`/`release` then solve against the region captured at press
    time, so the frame follows the pointer's offset instead of jumping under it.
    """

    # How close (px, per axis) to a corner turns a band grab into a resize.
    CORNER_GRAB_PX = 12

    def __init__(self, region: Region, aspect: str, screen_w: int, screen_h: int):
        self._region = region
        self._aspect = aspect
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._press: Optional[tuple] = None
        self._base: Optional[Region] = None
        self._mode: Mode = (MOVE, None)
        self._preview: Optional[Region] = None

    @property
    def region(self) -> Region:
        """What to display right now: the live preview while dragging."""
        return self._preview or self._region

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def dragging(self) -> bool:
        return self._press is not None

    def set_aspect(self, aspect: str) -> None:
        self._aspect = aspect

    def press(self, x: int, y: int) -> None:
        self._press = (x, y)
        self._base = self._region
        self._preview = None
        corner = self._corner_at(x, y)
        self._mode = (RESIZE, corner) if corner else (MOVE, None)

    def move(self, x: int, y: int) -> Region:
        if self._press is None:
            return self._region
        self._preview = self._solve(x, y)
        return self._preview

    def release(self, x: int, y: int) -> Optional[Region]:
        """Commit the drag. Returns the new region, or None when nothing moved."""
        if self._press is None:
            return None
        solved = self._solve(x, y)
        changed = solved != self._region
        self._region = solved
        self._press = None
        self._base = None
        self._preview = None
        return solved if changed else None

    def cancel(self) -> None:
        self._press = None
        self._base = None
        self._preview = None

    # -- internals --------------------------------------------------------
    def _solve(self, x: int, y: int) -> Region:
        base = self._base or self._region
        kind, corner = self._mode
        if kind == RESIZE and corner is not None:
            return resize_region_to_ratio(
                base, corner, x, y, self._aspect, self._screen_w, self._screen_h
            )
        px, py = self._press or (x, y)
        return move_region(
            base, x - px, y - py, self._screen_w, self._screen_h
        )

    def _corner_at(self, x: int, y: int) -> Optional[Corner]:
        """The corner within the grab radius of (x, y), if any (nearest wins)."""
        g = self.CORNER_GRAB_PX
        best: Optional[Corner] = None
        best_dist = None
        for corner, point in self._corners().items():
            dx, dy = abs(x - point[0]), abs(y - point[1])
            if dx > g or dy > g:
                continue
            dist = max(dx, dy)
            if best_dist is None or dist < best_dist:
                best, best_dist = corner, dist
        return best

    def _corners(self) -> dict:
        r = self._region
        right, bottom = r.x + r.w, r.y + r.h
        return {"tl": (r.x, r.y), "tr": (right, r.y),
                "bl": (r.x, bottom), "br": (right, bottom)}

    def probe(self, x: int, y: int) -> Mode:
        """The mode a press at (x, y) would take, without starting a drag."""
        corner = self._corner_at(x, y)
        return (RESIZE, corner) if corner else (MOVE, None)


def band_window_rects(region: Region, band: int, tab: "tuple[int, int]") -> dict:
    """The rectangle of each piece of the frame, every one outside `region`.

    (x, y, w, h) per piece. A side with no room (flush with the screen edge, or
    a tab that would run off screen) gets None, so that side simply draws and
    claims nothing rather than stepping into the recorded area.
    """
    x, y, w, h = region.x, region.y, region.w, region.h
    tx, ty = tab
    return {
        "top": (x, y - band, w, band),
        "bottom": (x, y + h, w, band),
        "left": (x - band, y, band, h),
        "right": (x + w, y, band, h),
        "tab": (x, y - band - ty, min(max(w, tx), tx), ty),
    }


class _Piece(QWidget):
    """One solid rectangle of the frame: a side strip, or the draggable label tab.

    Deliberately opaque and rectangular. A single window with a hollow mask was
    the first attempt, but on this X server a Qt mask changes only the BOUNDING
    shape -- the server kept reporting the full rectangle as the INPUT region and
    swallowed clicks over the recorded area (R3). Building the frame out of
    rectangles that simply do not exist over the region makes both invariants
    structural: nothing is painted inside it (R2) and nothing intercepts clicks
    inside it (R3).
    """

    def __init__(self, owner: "RegionFrame", role: str):
        super().__init__()
        self._owner = owner
        self._role = role
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # never steal focus

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        color = QColor(self._owner.RECORDING_COLOR if self._owner.locked else self._owner.IDLE_COLOR)
        painter.fillRect(self.rect(), color)
        self._owner.paint_marks(self, painter, self._role)
        painter.end()

    # -- input: forward globally, let the owner decide everything ----------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            p = event.globalPosition().toPoint()
            self._owner.begin_drag(p.x(), p.y())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        p = event.globalPosition().toPoint()
        if self._owner.dragging:
            self._owner.update_drag(p.x(), p.y())
            event.accept()
            return
        self._owner.update_cursor(p.x(), p.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            p = event.globalPosition().toPoint()
            self._owner.end_drag(p.x(), p.y())
            event.accept()

    def enterEvent(self, event) -> None:
        p = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else None
        if p is not None:
            self._owner.update_cursor(p.x(), p.y())
        super().enterEvent(event)


class RegionFrame(QObject):
    """The persistent, draggable frame around the selected region (R1, R2, R3, R6).

    Owns five small always-on-top rectangles laid out around the region. The
    region's own pixels are covered by no window at all, so the recording stays
    clean and the desktop underneath stays clickable while the frame is up.

    Signals:
        region_edited(object): the region the user dragged a piece to. Emitted on
            every real drag, locked or not -- the controller decides whether it
            lands, so the frame never gates writes itself (KTD4).
    """

    region_edited = Signal(object)

    BAND = 6              # thickness of each side strip, entirely outside the region
    TAB_MIN_WIDTH = 120   # the label tab is at least this wide so text fits
    MARK = 10             # corner bracket arm length, drawn inside the strips
    IDLE_COLOR = "#4FC3F7"
    RECORDING_COLOR = "#E53935"

    ROLES = ("top", "bottom", "left", "right", "tab")

    def __init__(self, screen_w: int, screen_h: int, parent=None):
        super().__init__(parent)
        self._screen_w = screen_w
        self._screen_h = screen_h
        self._model: Optional[RegionFrameModel] = None
        self._aspect = "16:9"
        self._locked = False
        self._dragging = False
        self._pieces = {role: _Piece(self, role) for role in self.ROLES}

    # -- lifecycle ----------------------------------------------------------
    def show_for(self, region: Region, aspect: str) -> None:
        """Display the frame around `region`, re-seeded with the live aspect."""
        self._aspect = aspect
        self._model = RegionFrameModel(region, aspect, self._screen_w, self._screen_h)
        self._layout()
        for piece in self._pieces.values():
            if piece.geometry().width() > 0 and piece.geometry().height() > 0:
                piece.show()
                piece.raise_()
            else:
                piece.hide()

    def clear(self) -> None:
        """Nothing to show: no region selected, or invalidated by an aspect change."""
        self._model = None
        self._dragging = False
        for piece in self._pieces.values():
            piece.hide()

    def is_visible(self) -> bool:
        return self._model is not None and any(
            p.isVisible() for p in self._pieces.values())

    def set_locked(self, locked: bool) -> None:
        """Recording style. Colour and cursor only -- never a write gate (KTD4)."""
        self._locked = locked
        for piece in self._pieces.values():
            piece.update()
            if locked:
                piece.setCursor(Qt.ForbiddenCursor)
            else:
                piece.unsetCursor()

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def model(self) -> Optional[RegionFrameModel]:
        return self._model

    def region(self) -> Optional[Region]:
        return None if self._model is None else self._model.region

    # -- geometry -----------------------------------------------------------
    def tab_height(self) -> int:
        from PySide6.QtGui import QFontMetrics
        metrics = QFontMetrics(self._pieces["tab"].font())
        return metrics.size(Qt.TextSingleLine, self.label_text()).height() + 6

    def label_text(self) -> str:
        prefix = "REC  " if self._locked else ""
        if self._model is None:
            return prefix
        r = self._model.region
        return f"{prefix}{r.w} x {r.h}  ({self._aspect})"

    def piece_rects(self) -> dict:
        """Global rect per piece; None where a side has no room to be drawn."""
        if self._model is None:
            return {role: None for role in self.ROLES}
        return band_window_rects(self._model.region, self.BAND,
                                 (self.tab_height(), self.tab_height()))

    def _layout(self) -> None:
        for role, rect in self.piece_rects().items():
            piece = self._pieces[role]
            if rect is None:
                piece.hide()
                continue
            piece.setGeometry(*rect)
            piece.update()

    def paint_marks(self, piece: QWidget, painter: QPainter, role: str) -> None:
        """Corner brackets and the tab's text, all inside the piece's own rect."""
        r = piece.rect()
        m = min(self.MARK, max(2, min(r.width(), r.height())))
        painter.setPen(QPen(QColor("white"), 2))
        if role in ("top", "bottom"):
            inner_y = r.height() - 1 if role == "top" else 0
            for x in (m, r.width() - 1 - m):
                painter.drawLine(QPoint(x - m, inner_y), QPoint(x + m, inner_y))
        elif role in ("left", "right"):
            inner_x = r.width() - 1 if role == "left" else 0
            for y in (m, r.height() - 1 - m):
                painter.drawLine(QPoint(inner_x, y - m), QPoint(inner_x, y + m))
        elif role == "tab":
            painter.setPen(QPen(QColor("white")))
            painter.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, self.label_text())

    # -- drag seam (also driven directly by tests) --------------------------
    def begin_drag(self, x: int, y: int) -> None:
        if self._model is None:
            return
        self._model.press(x, y)
        self._dragging = True
        self.update_cursor(x, y)

    def update_drag(self, x: int, y: int) -> None:
        if self._model is None or not self._dragging:
            return
        self._model.move(x, y)
        self._layout()

    def end_drag(self, x: int, y: int) -> Optional[Region]:
        if self._model is None:
            return None
        settled = self._model.release(x, y)
        self._dragging = False
        self._layout()
        if settled is not None:
            self.region_edited.emit(settled)
        return settled

    def update_cursor(self, x: int, y: int) -> None:
        if self._locked or self._model is None:
            return
        kind, corner = self._model.probe(x, y)
        cursor = (Qt.SizeFDiagCursor if corner in ("tl", "br") else Qt.SizeBDiagCursor) \
            if kind == RESIZE else Qt.SizeAllCursor
        for piece in self._pieces.values():
            if piece.underMouse():
                piece.setCursor(cursor)
