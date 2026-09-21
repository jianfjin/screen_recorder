"""The recording control strip's geometry and constants (pure, no Qt).

R2: nothing this app paints may land inside the recorded region. R3: the main
window only collapses when it actually covers part of that region. R5: where the
strip goes is decided by an algorithm, once, at the moment of collapsing.

The invariant this module exists to make checkable is a statement about
rectangles, so it stays a statement about rectangles here: no widget, no window,
no palette. `app/strip.py`'s counterpart in U2 is the thin top-level window that
gets *moved to* the rectangle `strip_placement` returns; if that window ever ends
up somewhere else, the geometry proved here stops being a proof about pixels.

Placement rule (KTD3): the four screen bands, in the fixed order
top -> bottom -> left -> right. A band qualifies only when *both* dimensions
clear: the gap on that side must hold the strip's thickness plus room for the
persistent frame's band, and the screen must be long enough along that edge for
the strip to run. First band that qualifies wins (first-fit, not best-fit), so a
nudged region keeps its strip on the same side. When none qualifies, the widest
gap wins, ties broken by that same order -- which is why a full-screen region
always lands on top, `inside` set, and gets recorded (AE3's documented
exception).

`inside` is *computed* from the rectangle, never asserted: it is exactly the
claim "this strip's pixels overlap the region". That is what makes R2 falsifiable
instead of a comment that hopes the algorithm is right.
"""
from __future__ import annotations

from dataclasses import dataclass

from .aspect import Region

BAR = "bar"            # horizontal: duration left, stop right (top and bottom bands)
STACKED = "stacked"    # vertical: duration above stop (left and right bands)

# The band order. Placement and the fallback tie-break share this one list (R5).
SIDE_ORDER = ("top", "bottom", "left", "right")
LAYOUT_OF = {"top": BAR, "bottom": BAR, "left": STACKED, "right": STACKED}

# The strip shows two things and nothing else (R4): the elapsed time, and the one
# button that stops the recording.
LABEL_SIZE = (88, 22)          # roomy enough for "HH:MM:SS" at the frame's font
STOP_BUTTON_SIZE = (72, 28)    # the only click target that has to work (R6, R7)
STRIP_INSET = 8                # padding between the contents and the edge
STRIP_GAP = 8                  # between the label and the button

# (w, h). Which dimension is the *thickness* (the one that has to clear a band)
# follows the layout: a bar lies down, a stacked strip stands up.
BAR_SIZE = (LABEL_SIZE[0] + STRIP_GAP + STOP_BUTTON_SIZE[0] + 2 * STRIP_INSET,
            max(LABEL_SIZE[1], STOP_BUTTON_SIZE[1]) + 2 * STRIP_INSET)          # (184, 44)
STACKED_SIZE = (max(LABEL_SIZE[0], STOP_BUTTON_SIZE[0]) + 2 * STRIP_INSET,
                LABEL_SIZE[1] + STRIP_GAP + STOP_BUTTON_SIZE[1] + 2 * STRIP_INSET)  # (104, 74)


@dataclass(frozen=True)
class StripSizes:
    """The strip's size per layout.

    A caller may hand a smaller pair to `strip_placement` to ask what would fit;
    the geometry never assumes the default.
    """

    bar: tuple = BAR_SIZE
    stacked: tuple = STACKED_SIZE

    def for_layout(self, layout: str) -> tuple:
        return self.bar if layout == BAR else self.stacked


STRIP_SIZES = StripSizes()

# Room kept for the persistent region frame (app/frame.py), which stays on screen
# while recording and must not end up underneath the strip (R6). `BAND_RESERVE`
# is pinned to RegionFrame.BAND -- the tests say so, since importing the frame
# here would import Qt. The top band carries the frame's label tab as well, and
# that stands a further text line above its own band, hence the extra reserve.
BAND_RESERVE = 6               # >= RegionFrame.BAND
LABEL_TAB_RESERVE = 20         # >= RegionFrame.tab_height() as this box draws it

# Colours, set explicitly by the widget (KTD7) -- never inherited from the Qt
# palette, whose Window grey is within 16 of the frame's white marks and would
# make a leaked strip read as a leaked frame. Both stay >= 41 away from every
# colour the U4 oracle already treats as a violation, per channel, so a strip
# leak can be told apart from a frame leak. Neither is a colour ordinary desktop
# content draws, so neither hides in it.
BACKGROUND_COLOR = "#1C0008"   # (28, 0, 8)
TEXT_COLOR = "#B40CC4"         # (180, 12, 196)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _hug(extent, size) -> int:
    """The coordinate that puts `size` flush against the far end of `extent`.

    Clamped at 0: a strip deeper than the screen has no edge to hug, and negative
    coordinates are the one thing a placement must never return.
    """
    return _clamp(extent - size, 0, extent)


def _centred(extent, size) -> int:
    """The coordinate that centres `size` along an `extent`-long edge, never negative."""
    return max(0, (extent - size) // 2)


def _box(shape) -> tuple:
    """(x, y, w, h) from a `Region`, or from a plain rectangle tuple.

    A caller holding a `QRect` passes `rect.getRect()`, which is already this
    shape -- that keeps Qt out of this module and out of its tests.
    """
    if isinstance(shape, Region):
        return shape.x, shape.y, shape.w, shape.h
    x, y, w, h = shape
    return x, y, w, h


def _intersects(left, right) -> bool:
    """Do two rectangles share a pixel?

    Half-open on purpose: sharing an edge is touching, not covering, and that is
    the same convention the persistent frame's bands rely on when they stop at the
    region edge. A rectangle without area covers no pixels, so it shares none.
    """
    ax, ay, aw, ah = left
    bx, by, bw, bh = right
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _thickness(layout, strip_size) -> int:
    """The strip's reach across the band it sits in."""
    w, h = strip_size.for_layout(layout)
    return h if layout == BAR else w


def _length(layout, strip_size) -> int:
    """The strip's reach along the band it sits in."""
    w, h = strip_size.for_layout(layout)
    return w if layout == BAR else h


def _run(side, screen_w, screen_h) -> int:
    """How far there is to run along that screen edge."""
    return screen_w if LAYOUT_OF[side] == BAR else screen_h


def reserve_for(side: str) -> int:
    """How much of a band the frame's pieces already own before the strip starts."""
    return BAND_RESERVE + LABEL_TAB_RESERVE if side == "top" else BAND_RESERVE


def min_gap_for(side: str, strip_size: StripSizes = STRIP_SIZES) -> int:
    """The gap that side needs for the strip to fit: thickness plus the frame's reserve."""
    return _thickness(LAYOUT_OF[side], strip_size) + reserve_for(side)


def _gaps(region, screen_w, screen_h) -> dict:
    """Free pixels between the region and each screen edge, in the band's own direction."""
    x, y, w, h = _box(region)
    return {"top": y, "bottom": screen_h - (y + h), "left": x, "right": screen_w - (x + w)}


def _rect_for(side, screen_w, screen_h, strip_size) -> tuple:
    """The strip hugging that screen edge, centred along it, never at a negative coordinate.

    Centring a strip longer than the edge asks for a negative offset; `max(0, ...)`
    keeps it on the screen side, and the run test in `strip_placement` is what stops
    such a band from being offered in the first place.
    """
    w, h = strip_size.for_layout(LAYOUT_OF[side])
    if side == "top":
        return (_centred(screen_w, w), 0, w, h)
    if side == "bottom":
        return (_centred(screen_w, w), _hug(screen_h, h), w, h)
    if side == "left":
        return (0, _centred(screen_h, h), w, h)
    return (_hug(screen_w, w), _centred(screen_h, h), w, h)


def should_collapse(window_rect, region) -> bool:
    """Does the app's own window sit on pixels that are about to be recorded?

    `window_rect` is the window's *global frame* rectangle -- `(x, y, w, h)`, i.e.
    `QWidget.frameGeometry().getRect()`, decorations included, because decorated
    pixels are on the desktop and in the recording too. `pos()` plus a fixed size
    is not enough: on this box that rectangle is 604x194 at (300, 200) where
    `geometry()` reports 600x190 at (302, 202), and a 2px overestimate of the
    region's edge is exactly a window edge peeking into the capture (KTD4).

    R3 in one line: no overlap, no collapse, business as usual.
    """
    return _intersects(_box(window_rect), _box(region))


def strip_placement(region, screen_w, screen_h, strip_size: StripSizes = STRIP_SIZES):
    """Where the strip goes: `(rect, side, layout, inside)`.

    First-fit over the bands in `SIDE_ORDER`; a band must clear both dimensions
    (see the module docstring), and a band that fails either is skipped rather
    than squeezed in. No band fits -> the widest gap, ties by the same order, and
    `inside` says what that costs: the strip is on the region and will be recorded
    (AE3). Nothing here special-cases a region flush with an edge -- a 0 gap loses
    the fit test on its own.
    """
    box = _box(region)
    gaps = _gaps(box, screen_w, screen_h)

    for side in SIDE_ORDER:
        if gaps[side] >= min_gap_for(side, strip_size) and _run(side, screen_w, screen_h) >= _length(
                LAYOUT_OF[side], strip_size):
            # Both dimensions cleared, so this band is genuinely outside the region.
            return _rect_for(side, screen_w, screen_h, strip_size), side, LAYOUT_OF[side], False

    # Fallback: max() keeps the first of equal maxima, so ties follow the order.
    side = max(SIDE_ORDER, key=lambda candidate: gaps[candidate])
    rect = _rect_for(side, screen_w, screen_h, strip_size)
    return rect, side, LAYOUT_OF[side], _intersects(rect, box)
