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
