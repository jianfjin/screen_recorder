"""Strip model — the pure geometry behind the recording control strip (R2, R3, R5).

Two questions, both answerable without a window server: does the main window's
frame rectangle actually overlap the region (R3: only then do we collapse), and
where does the strip go (R5: first-fit over the four screen bands, else the
widest band with `inside` set).

No Qt types are involved, which is the whole point: "the strip never paints
inside the recorded area" is a claim about rectangles, so it is exhausted here
rather than sampled by eye. What cannot be proved offscreen is that the real
strip window is the rectangle this module picked, that its stop button is
clickable without activating anything, and that no pixel of it reaches the
recording; those are the U2 wiring tests and the live-X rows of the plan's
Verification Contract.

Two tests do touch Qt on purpose (the `RegionFrame` reserve pins): the strip's
reserve is only meaningful while it tracks the frame it must clear.
"""
import itertools

import pytest

from app import strip
from app.aspect import Region
from app.frame import RegionFrame

SCREEN_W, SCREEN_H = 3440, 1440
BASE = Region(400, 300, 640, 360)

# Every colour the U4 pixel oracle already treats as "this app leaked" (KTD7).
# The strip's own colours must stay this far away per channel, or a strip leak
# would be reported as a frame leak.
MIN_CHANNEL_DISTANCE = 41
REFERENCE_COLOURS = {
    "frame idle #4FC3F7": (0x4F, 0xC3, 0xF7),
    "frame recording #E53935": (0xE5, 0x39, 0x35),
    "frame marks #FFFFFF": (255, 255, 255),
    "e2e canvas grey": (128, 128, 128),
}


def place(region=BASE, sizes=strip.STRIP_SIZES, screen=(SCREEN_W, SCREEN_H)):
    return strip.strip_placement(region, screen[0], screen[1], sizes)


def rgb(hex_colour):
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def overlaps(rect, region):
    """Do these rectangles share a pixel? An edge in common is not a pixel.

    Written from the definition rather than from the module's helper, so that this
    stays a check on the answer and not a copy of the code under test.
    """
    x, y, w, h = rect
    if w <= 0 or h <= 0 or region.w <= 0 or region.h <= 0:
        return False        # a rectangle without area is on no pixels
    return x < region.x + region.w and region.x < x + w and y < region.y + region.h and region.y < y + h


def gap(side, region, screen=(SCREEN_W, SCREEN_H)):
    sw, sh = screen
    return {"top": region.y,
            "bottom": sh - (region.y + region.h),
            "left": region.x,
            "right": sw - (region.x + region.w)}[side]


def contrast(colour_a, colour_b):
    def luminance(c):
        def linear(v):
            v = v / 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * linear(c[0]) + 0.7152 * linear(c[1]) + 0.0722 * linear(c[2])
    hi, lo = sorted((luminance(colour_a), luminance(colour_b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def centre_run(side, screen=(SCREEN_W, SCREEN_H)):
    """How much room there is to run along the edge `side` names."""
    return screen[0] if side in ("top", "bottom") else screen[1]


# A grid wide enough to include every interesting degeneracy: flush with each
# edge and corner, 1px insets, a 1px region, an empty one, and regions bigger
# than the screen. Every placement answer below is checked on all of them.
SWEEP_POSITIONS = itertools.product((0, 1, 70, 110, 1620, 3330, 3439),
                                    (0, 1, 50, 70, 700, 1390, 1439))
SWEEP_SIZES = ((0, 360), (1, 1), (640, 360), (3220, 1320), (3440, 1440), (4000, 2000))
SWEEP_REGIONS = [Region(x, y, w, h) for (x, y), (w, h)
                 in itertools.product(SWEEP_POSITIONS, SWEEP_SIZES)]


# --------------------------------------------------------------------------
# R3 — should the interface collapse at all?
# --------------------------------------------------------------------------
@pytest.mark.parametrize("window", [
    (300, 300, 604, 194),    # overlaps by exactly 1px on its right edge
    (1037, 300, 604, 194),   # overlaps by exactly 1px on its left edge
    (400, 657, 604, 194),    # overlaps by exactly 1px on its top edge
    (400, 107, 604, 194),    # reaches down 1px into the region
    (420, 320, 604, 194),    # sits on top of the region
    (100, 100, 4000, 2000),  # contains it
    (500, 400, 64, 64),      # is contained by it
])
def test_a_window_that_covers_pixels_of_the_region_must_collapse(window):
    assert strip.should_collapse(window, BASE) is True


@pytest.mark.parametrize("window", [
    (0, 300, 399, 194),      # 1px short of the region's left edge
    (1041, 300, 604, 194),   # 1px short of its right edge
    (400, 100, 604, 199),    # 1px above it
    (400, 661, 604, 194),    # 1px below it
    (0, 0, 604, 194),        # the whole window in the top band, clear of the region
    (2800, 1000, 604, 194),  # off in the bottom-right corner of the screen
])
def test_a_window_that_covers_none_of_the_region_stays_put(window):
    assert strip.should_collapse(window, BASE) is False


@pytest.mark.parametrize("window", [
    (0, 300, 400, 194),     # right edge lands exactly on the region's x
    (1040, 300, 604, 194),  # left edge lands exactly on the region's right edge
    (400, 100, 604, 200),   # bottom edge lands exactly on the region's y
    (400, 660, 604, 194),   # top edge lands exactly on the region's bottom edge
])
def test_sharing_an_edge_is_not_covering_any_pixel(window):
    # Same half-open convention the persistent frame uses: its bands stop at the
    # region edge and are never "inside" it.
    assert strip.should_collapse(window, BASE) is False


def test_an_empty_window_rectangle_covers_no_pixels():
    assert strip.should_collapse((500, 400, 0, 194), BASE) is False
    assert strip.should_collapse((500, 400, 604, 0), BASE) is False
    assert strip.should_collapse((0, 0, 0, 0), BASE) is False


def test_a_one_pixel_region_is_still_a_region():
    pinprick = Region(700, 500, 1, 1)
    assert strip.should_collapse((699, 499, 2, 2), pinprick) is True
    assert strip.should_collapse((700, 500, 1, 1), pinprick) is True
    assert strip.should_collapse((701, 500, 1, 1), pinprick) is False


# --------------------------------------------------------------------------
# The constants U2 and the U4 oracle depend on
# --------------------------------------------------------------------------
def test_the_band_reserve_is_pinned_to_the_frame_band_it_must_clear():
    assert strip.BAND_RESERVE >= RegionFrame.BAND
    # left/right/bottom clear nothing but the band; top also clears the label tab
    assert strip.reserve_for("bottom") == strip.BAND_RESERVE
    assert strip.reserve_for("left") == strip.BAND_RESERVE
    assert strip.reserve_for("right") == strip.BAND_RESERVE
    assert strip.reserve_for("top") == strip.BAND_RESERVE + strip.LABEL_TAB_RESERVE


def test_the_top_reserve_reaches_past_the_label_tab_as_the_frame_draws_it():
    frame = RegionFrame(SCREEN_W, SCREEN_H)
    frame.show_for(BASE, "16:9")
    tab = frame.piece_rects()["tab"]
    try:
        assert strip.LABEL_TAB_RESERVE >= tab[3] >= frame.tab_height() > 0
        # ... and the tab really does stand above the band the strip shares.
        assert strip.reserve_for("top") >= RegionFrame.BAND + tab[3]
    finally:
        frame.clear()


def test_the_two_layouts_have_explicit_sizes():
    assert strip.BAR_SIZE == (184, 44)          # time label | stop, side by side
    assert strip.STACKED_SIZE == (104, 74)      # time label above stop
    assert strip.STRIP_SIZES.bar == strip.BAR_SIZE
    assert strip.STRIP_SIZES.stacked == strip.STACKED_SIZE


@pytest.mark.parametrize("colour_name", ["BACKGROUND_COLOR", "TEXT_COLOR"])
def test_the_strip_colours_are_distinguishable_from_every_reference_colour(colour_name):
    colour = rgb(getattr(strip, colour_name))
    assert len(colour) == 3 and all(0 <= c <= 255 for c in colour)
    for reference, ref_rgb in REFERENCE_COLOURS.items():
        per_channel = [abs(a - b) for a, b in zip(colour, ref_rgb)]
        assert min(per_channel) >= MIN_CHANNEL_DISTANCE, (
            f"{colour_name} {colour} is only {min(per_channel)}px from {reference} "
            f"in channel {per_channel.index(min(per_channel))}")


def test_the_strip_label_is_readable_on_its_own_background():
    # The two strip colours must not be each other, and the label has to be
    # readable: 3:1 is the floor for the large timer text.
    assert strip.BACKGROUND_COLOR != strip.TEXT_COLOR
    assert contrast(rgb(strip.BACKGROUND_COLOR), rgb(strip.TEXT_COLOR)) >= 3.0


# --------------------------------------------------------------------------
# R5 — where the strip goes
# --------------------------------------------------------------------------
def test_a_region_flush_with_the_top_edge_takes_the_bottom_band():
    # AE2: the selection hugs the top of the screen and the bottom is empty.
    region = Region(1400, 12, 640, 360)
    rect, side, layout, inside = place(region)
    assert (side, layout, inside) == ("bottom", "bar", False)
    assert rect[1] + rect[3] == SCREEN_H
    assert overlaps(rect, region) is False
    # The reason top loses while bottom wins is the label tab, which only stands
    # above the top band: R6's "neither covers the other" is arithmetic here.
    assert strip.min_gap_for("top") > strip.min_gap_for("bottom")


@pytest.mark.parametrize("side", ["top", "bottom", "left", "right"])
def test_the_strip_hugs_its_edge_and_is_centred_along_it(side):
    region = {"top": Region(110, 70, 3220, 1330),
              "bottom": Region(110, 20, 3220, 1370),
              "left": Region(110, 20, 3200, 1380),
              "right": Region(109, 20, 3221, 1380)}[side]
    rect, chosen, layout, inside = place(region)
    assert chosen == side
    assert inside is False
    assert overlaps(rect, region) is False
    x, y, w, h = rect
    assert x >= 0 and y >= 0
    if side == "top":
        assert (y, layout) == (0, "bar")
    elif side == "bottom":
        assert (y + h, layout) == (SCREEN_H, "bar")
    elif side == "left":
        assert (x, layout) == (0, "stacked")
    else:
        assert (x + w, layout) == (SCREEN_W, "stacked")
    if layout == "bar":
        assert (w, h) == strip.BAR_SIZE
        assert x == (SCREEN_W - w) // 2
    else:
        assert (w, h) == strip.STACKED_SIZE
        assert y == (SCREEN_H - h) // 2


@pytest.mark.parametrize("side", ["top", "bottom", "left", "right"])
def test_a_gap_exactly_at_the_threshold_fits(side):
    region = {"top": Region(110, 70, 3220, 1330),
              "bottom": Region(110, 20, 3220, 1370),
              "left": Region(110, 20, 3200, 1380),
              "right": Region(109, 20, 3221, 1380)}[side]
    assert gap(side, region) == strip.min_gap_for(side)
    assert place(region)[1] == side


@pytest.mark.parametrize("side", ["top", "bottom", "left", "right"])
def test_one_pixel_less_than_the_threshold_skips_that_side(side):
    shrink = {"top": lambda r: Region(r.x, r.y - 1, r.w, r.h + 1),
              "bottom": lambda r: Region(r.x, r.y, r.w, r.h + 1),
              "left": lambda r: Region(r.x - 1, r.y, r.w + 1, r.h),
              "right": lambda r: Region(r.x, r.y, r.w + 1, r.h)}[side]
    region = shrink({"top": Region(110, 70, 3220, 1330),
                     "bottom": Region(110, 20, 3220, 1370),
                     "left": Region(110, 20, 3200, 1380),
                     "right": Region(109, 20, 3221, 1380)}[side])
    assert gap(side, region) == strip.min_gap_for(side) - 1
    rect, chosen, layout, inside = place(region)
    assert chosen != side
    assert rect[0] >= 0 and rect[1] >= 0


def test_first_fit_is_first_fit_not_best_fit():
    # 300px free above, 500px below: both clear the bar. The order decides.
    region = Region(400, 300, 640, 640)
    assert gap("top", region) < gap("bottom", region)
    rect, side, layout, inside = place(region)
    assert side == "top" and layout == "bar" and inside is False
    assert rect[1] == 0


def test_the_top_reserve_includes_the_label_tab_not_just_the_band():
    # A gap that would be plenty for the other three sides still loses up here,
    # because the frame's label tab stands on top of the band.
    band_only = strip.BAR_SIZE[1] + strip.BAND_RESERVE
    assert band_only < strip.min_gap_for("top")
    region = Region(110, band_only, 3220, SCREEN_H - band_only - 40)
    rect, side, layout, inside = place(region)
    assert side != "top"
    assert inside is False and overlaps(rect, region) is False


def test_a_deep_enough_band_that_is_too_short_along_the_edge_is_no_band():
    # 160px of screen width: the top band is 400px deep, but a 184px bar cannot
    # run along a 160px edge, so it must not be clamped into negative x.
    sizes = strip.StripSizes(bar=(900, 44), stacked=strip.STACKED_SIZE)
    region = Region(120, 400, 30, 600)
    rect, side, layout, inside = place(region, sizes, (160, 1400))
    assert side == "left" and layout == "stacked" and inside is False
    assert rect[0] >= 0
    # Control: with a bar short enough to run along that edge, top wins again.
    short = strip.StripSizes(bar=(120, 44), stacked=strip.STACKED_SIZE)
    assert place(region, short, (160, 1400))[1] == "top"


def test_the_along_edge_run_is_checked_on_the_left_and_right_bands_too():
    # A 3440x300 screen: the left band is deep enough for a stacked strip, but
    # the strip could never run down a 300px edge, so that band is void.
    sizes = strip.StripSizes(bar=strip.BAR_SIZE, stacked=(104, 900))
    region = Region(200, 30, 40, 230)
    assert gap("left", region, (3440, 300)) >= strip.min_gap_for("left")
    assert centre_run("left", (3440, 300)) < sizes.stacked[1]
    rect, side, layout, inside = place(region, sizes, (3440, 300))
    # The fallback takes the widest gap (right, 3200px). That rect really does
    # miss the region, so `inside` is False even on this branch: the answer is
    # computed from the geometry, not asserted by the branch that produced it.
    assert (side, layout, inside) == ("right", "stacked", False)
    assert rect[0] >= 0 and rect[1] >= 0
    # Control: with the real stacked size the same region picks the left band.
    assert place(region, strip.STRIP_SIZES, (3440, 300))[:2] == ((0, 113, 104, 74), "left")


@pytest.mark.parametrize("region,expected", [
    (Region(30, 20, 3370, 1390), "right"),    # 40 > 30 = 30 > 20: right is widest
    (Region(20, 20, 3400, 1390), "bottom"),   # 30 is the one widest gap
])
def test_when_no_band_fits_the_widest_gap_wins(region, expected):
    rect, side, layout, inside = place(region)
    assert side == expected
    assert inside is True
    assert max(gap(s, region) for s in ("top", "bottom", "left", "right")) == gap(side, region)


def test_a_tie_in_the_fallback_follows_the_same_side_order():
    # left and right are both 100px and both too narrow: left is earlier.
    region = Region(100, 20, 3240, 1400)
    assert gap("left", region) == gap("right", region)
    assert place(region)[1] == "left"


@pytest.mark.parametrize("region", [
    Region(0, 0, 3440, 1440),     # the whole screen
    Region(0, 0, 3441, 1441),     # one pixel more than the screen, both axes
    Region(-50, -50, 4000, 2000),  # larger than the screen, offset off it
])
def test_no_band_at_all_lands_on_top_in_the_tie_order(region):  # AE3
    rect, side, layout, inside = place(region)
    assert (side, layout, inside) == ("top", "bar", True)
    assert rect[0] >= 0 and rect[1] >= 0
    assert rect[2] == strip.BAR_SIZE[0] and rect[3] == strip.BAR_SIZE[1]
    assert place(region) == (rect, side, layout, inside)


def test_a_region_flush_with_the_left_edge_is_not_an_excuse_for_a_negative_x():
    region = Region(0, 20, 300, 1400)   # left gap 0, top and bottom narrow
    rect, side, layout, inside = place(region)
    assert side == "right" and inside is False
    assert rect[0] >= 0 and rect[1] >= 0
    assert rect[0] + rect[2] <= SCREEN_W


# --------------------------------------------------------------------------
# R2 — the constructive proofs
# --------------------------------------------------------------------------
@pytest.mark.parametrize("region", SWEEP_REGIONS)
def test_inside_is_exactly_the_statement_that_the_strip_touches_the_region(region):
    rect, side, layout, inside = place(region)
    assert inside is (overlaps(rect, region))
    assert (inside is False) == (overlaps(rect, region) is False)  # R2, machine-checkable
    # The soundness half of that: a band with room for the strip is never inside.
    # (A band without room can still miss the region -- the reserve it fails is for
    # the frame's label tab, not for the region -- so this direction is the one
    # that holds, and `inside` never has to.)
    length = rect[2] if layout == "bar" else rect[3]
    if gap(side, region) >= strip.min_gap_for(side) and centre_run(side) >= length:
        assert inside is False


@pytest.mark.parametrize("region", SWEEP_REGIONS)
def test_the_model_is_a_function_of_its_input(region):
    assert place(region) == place(region) == place(region)


@pytest.mark.parametrize("region", SWEEP_REGIONS)
def test_the_strip_is_never_placed_off_the_top_left_of_the_screen(region):
    rect, side, layout, inside = place(region)
    assert rect[0] >= 0 and rect[1] >= 0
    assert rect[2] > 0 and rect[3] > 0
    assert (layout == "bar") == (side in ("top", "bottom"))
    assert (rect[2], rect[3]) == (strip.BAR_SIZE if layout == "bar" else strip.STACKED_SIZE)
