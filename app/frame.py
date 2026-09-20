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
