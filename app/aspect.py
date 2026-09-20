"""Aspect-locked region selection math (pure, no Qt).

R2: aspect is chosen before recording. R3: the drag rectangle is always
constrained to the chosen ratio. R4: 1080p targets per aspect.
"""
from __future__ import annotations

from dataclasses import dataclass

ASPECTS = {
    "16:9": (16, 9),
    "3:2": (3, 2),
}

DEFAULT_ASPECT = "16:9"

# Fixed 1080p output targets per aspect (KTD5 / R4).
TARGETS = {
    "16:9": (1920, 1080),
    "3:2": (1620, 1080),
}

# Minimum pixels on the shorter side of a usable region.
MIN_SHORT_SIDE = 64


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int

    def as_qrect(self):
        """Return a Qt.QRect for painting (imported lazily to keep module pure)."""
        from PySide6.QtCore import QRect
        return QRect(self.x, self.y, self.w, self.h)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def snap_to_ratio(x0, y0, x1, y1, aspect, screen_w, screen_h):
    """Snap a drag from (x0, y0) to (x1, y1) to a rectangle locked to `aspect`.

    The rectangle is anchored at the drag start and extends in the drag
    direction. The result is clamped inside the screen and is at least
    MIN_SHORT_SIDE px on its shorter side.
    """
    num, den = ASPECTS[aspect]
    left, right = (x0, x1) if x1 >= x0 else (x1, x0)
    top, bottom = (y0, y1) if y1 >= y0 else (y1, y0)
    raw_w = max(1, right - left)
    raw_h = max(1, bottom - top)

    # The dimension that overshoots the target ratio drives the size; the
    # other dimension is derived from it so the ratio holds.
    if raw_w * den >= raw_h * num:
        w = raw_w
        h = max(1, round(w * den / num))
    else:
        h = raw_h
        w = max(1, round(h * num / den))

    # Enforce the minimum size on the shorter side.
    if w < round(MIN_SHORT_SIDE * num / den):
        w = round(MIN_SHORT_SIDE * num / den)
        h = max(1, round(w * den / num))
    if h < MIN_SHORT_SIDE:
        h = MIN_SHORT_SIDE
        w = max(1, round(h * num / den))

    # Shrink to fit the screen if needed (ratio preserved).
    if w > screen_w or h > screen_h:
        if screen_w / w <= screen_h / h:
            w = max(1, screen_w)
            h = max(1, round(w * den / num))
        else:
            h = max(1, screen_h)
            w = max(1, round(h * num / den))

    # Anchor at the drag start, extend in the drag direction, clamp to screen.
    x = x0 if x1 >= x0 else x0 - w
    y = y0 if y1 >= y0 else y0 - h
    x = _clamp(x, 0, screen_w - w)
    y = _clamp(y, 0, screen_h - h)
    return Region(x, y, w, h)

def move_region(region, dx, dy, screen_w, screen_h):
    """Translate `region` by (dx, dy), keeping its size and staying on screen.

    Used by the persistent frame's border drag: the offset is taken from the
    press point, so grabbing the band anywhere moves the frame by how far the
    pointer travelled rather than teleporting it under the cursor.
    """
    x = _clamp(region.x + dx, 0, max(0, screen_w - region.w))
    y = _clamp(region.y + dy, 0, max(0, screen_h - region.h))
    return Region(x, y, region.w, region.h)


# corner key -> (anchor corner key, x direction from anchor, y direction)
_CORNERS = ("tl", "tr", "bl", "br")


def _anchor_corner(region, corner):
    """The corner opposite the one being dragged, as (x, y, sign_x, sign_y).

    `sign_*` is the direction the rectangle grows from the anchor, so the
    resize math can always run in a positive anchor-relative space.
    """
    right, bottom = region.x + region.w, region.y + region.h
    return {
        "br": (region.x, region.y, 1, 1),
        "bl": (right, region.y, -1, 1),
        "tr": (region.x, bottom, 1, -1),
        "tl": (right, bottom, -1, -1),
    }[corner]


def resize_region_to_ratio(region, corner, x, y, aspect, screen_w, screen_h):
    """Resize `region` by dragging `corner` to (x, y), locked to `aspect`.

    The opposite corner is the anchor and is returned exactly where it was.
    `snap_to_ratio` does the ratio solve, the minimum size, and the shrink to
    fit, but it clamps *position* against the whole screen -- so it is called
    here in anchor-relative space with the space that remains from the anchor.
    Handing it absolute coordinates instead makes the anchor slide (from
    (1000, 900) on a 3440x1440 screen it returns y=90), turning a resize into a
    move.
    """
    ax, ay, sx, sy = _anchor_corner(region, corner)
    avail_w = max(1, (screen_w - ax) if sx > 0 else ax)
    avail_h = max(1, (screen_h - ay) if sy > 0 else ay)
    px = _clamp(sx * (x - ax), 1, avail_w)
    py = _clamp(sy * (y - ay), 1, avail_h)
    rel = snap_to_ratio(0, 0, px, py, aspect, avail_w, avail_h)
    rx = ax + rel.x if sx > 0 else ax - rel.x - rel.w
    ry = ay + rel.y if sy > 0 else ay - rel.y - rel.h
    return Region(rx, ry, rel.w, rel.h)
