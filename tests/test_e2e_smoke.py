"""Real-capture end-to-end smoke tests.

Gated: only runs when RUN_E2E=1, ffmpeg is present, and an X DISPLAY is set.
The first two drive the actual encoder against the live X server (AE2/AE3) and
the no-audio variant (F2), then verify the output with ffprobe.

The last two (U4 / R2 / AE4) go further and read the recorded pixels, to prove
that no part of the persistent region frame ever lands inside a recording.
That needs real windows on a real display, so the GUI half runs in a child
process (tests/e2e_frame_host.py) -- this one already owns an offscreen
QApplication, and Qt permits only one per process -- and everything it leaves
behind is inspected here.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.aspect import Region
from app.encoder import Recorder, build_args

REPO_ROOT = Path(__file__).resolve().parents[1]


def _has_env() -> bool:
    return (
        os.environ.get("RUN_E2E") == "1"
        and shutil.which("ffmpeg") is not None
        and bool(os.environ.get("DISPLAY"))
    )


def _ffprobe_streams(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)["streams"]


def _record(with_audio: bool, tmp_path, seconds: float = 3.0):
    # 16:9 region smaller than 1080p -> scale up to 1920x1080 (AE2).
    region = Region(0, 0, 1280, 720)
    out = tmp_path / f"e2e_audio{int(with_audio)}_{int(time.time())}.mp4"
    args = build_args(region, "16:9", out, with_audio=with_audio)
    rec = Recorder(args)
    rec.start()
    time.sleep(seconds)
    rec.stop()
    return out


def test_e2e_with_audio_is_1080p_h264_aac(tmp_path):
    if not _has_env():
        pytest.skip("real capture e2e needs RUN_E2E=1, ffmpeg, and an X DISPLAY")
    out = _record(True, tmp_path)
    assert out.exists() and out.stat().st_size > 0
    streams = _ffprobe_streams(out)
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    assert video and video[0]["codec_name"] == "h264"
    assert video[0]["width"] == 1920 and video[0]["height"] == 1080
    assert audio and audio[0]["codec_name"] == "aac"


def test_e2e_silent_path_is_video_only(tmp_path):
    if not _has_env():
        pytest.skip("real capture e2e needs RUN_E2E=1, ffmpeg, and an X DISPLAY")
    out = _record(False, tmp_path)
    assert out.exists() and out.stat().st_size > 0
    streams = _ffprobe_streams(out)
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    assert video and video[0]["codec_name"] == "h264"
    assert not audio, "silent path must produce no audio stream"


# ---------------------------------------------------------------------------
# KTD2 / R2 / AE4: the frame's own pixels must never reach the recording.
# ---------------------------------------------------------------------------

COLOUR_TOL = 40          # how close two rgb values must be to call them the same
CANVAS_SPREAD = 16       # a canvas pixel stays this neutral in hue
CANVAS_DARK_SLACK = 40   # how far a canvas pixel may darken and still be canvas
CANVAS_LIGHT_SLACK = 25


def _rgb(hex_colour: str):
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def _close(a, b, tol=COLOUR_TOL):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _pixel(data, width, x, y):
    i = (y * width + x) * 3
    return (data[i], data[i + 1], data[i + 2])


def _read_raw(path: Path, width: int, height: int) -> bytes:
    data = path.read_bytes()
    assert len(data) == width * height * 3, (
        f"{path.name} holds {len(data)} bytes, not a {width}x{height} rgb24 frame")
    return data


def _run_frame_host(tmp_path, region: Region, tag: str, drag=None) -> dict:
    """Show the real windows on the live display, record, and collect the output."""
    art = tmp_path / f"host_{tag}"
    video = art / "capture.mp4"
    proc = subprocess.run(
        [sys.executable, "-m", "tests.e2e_frame_host",
         "--region", f"{region.x},{region.y},{region.w},{region.h}",
         "--out", str(video), "--art-dir", str(art),
         "--display", os.environ["DISPLAY"]]
        + (["--drag-while-recording", f"{drag[0]},{drag[1]}"] if drag else []),
        cwd=str(REPO_ROOT),
        env={**os.environ, "QT_QPA_PLATFORM": "xcb"},
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode == 2:      # the host knows the screen it was given
        pytest.skip(f"live display cannot host this check: {proc.stderr.strip()}")
    assert proc.returncode == 0, (
        f"the live-X host exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    manifest = json.loads((art / "manifest.json").read_text())
    manifest["video"] = video
    return manifest


def _assert_frame_never_enters_the_capture(tmp_path, region: Region, tag: str, drag=None):
    manifest = _run_frame_host(tmp_path, region, tag, drag=drag)
    screen_w, screen_h = manifest["screen"]
    gray = manifest["gray"]
    band = manifest["band"]
    idle_rgb, rec_rgb = _rgb(manifest["idle_color"]), _rgb(manifest["recording_color"])
    frame_colours = (idle_rgb, rec_rgb, (255, 255, 255))  # bands, and their marks

    def is_frame(p):
        return any(_close(p, colour) for colour in frame_colours)

    def is_canvas(p):
        return (max(p) - min(p) <= CANVAS_SPREAD
                and gray[0] - CANVAS_DARK_SLACK <= min(p)
                and max(p) <= gray[0] + CANVAS_LIGHT_SLACK)

    # 1. The frame is genuinely on the desktop -- band by band, in both styles --
    #    and the canvas genuinely covers the region. Skip this and the pixel
    #    check below would pass on an empty desktop having proved nothing.
    centres = {
        "top": (region.x + region.w // 2, region.y - band // 2),
        "bottom": (region.x + region.w // 2, region.y + region.h + band // 2),
        "left": (region.x - band // 2, region.y + region.h // 2),
        "right": (region.x + region.w + band // 2, region.y + region.h // 2),
    }
    on_screen = {side: point for side, point in centres.items()
                 if 0 <= point[0] < screen_w and 0 <= point[1] < screen_h}
    assert on_screen, "no frame band is on screen to verify"
    inside = {
        "centre": (region.x + region.w // 2, region.y + region.h // 2),
        "just inside the top": (region.x + region.w // 2, region.y + band),
        "just inside the bottom": (region.x + region.w // 2, region.y + region.h - band - 1),
        "just inside the left": (region.x + band, region.y + region.h // 2),
        "just inside the right": (region.x + region.w - band - 1, region.y + region.h // 2),
    }
    for style, key, expected in (("idle", "idle", idle_rgb),
                                 ("while recording", "recording", rec_rgb)):
        grab = _read_raw(Path(manifest["grabs"][key]), screen_w, screen_h)
        for side, (x, y) in sorted(on_screen.items()):
            p = _pixel(grab, screen_w, x, y)
            assert _close(p, expected), (
                f"the {side} band is not on screen {style}: found {p} at "
                f"({x},{y}), expected {expected}. Without a frame actually "
                f"painted, a clean recording proves nothing. If the whole "
                f"screen reads dark here, the session was blanked or locked "
                f"mid-run rather than the frame being absent.")
        for where, (x, y) in sorted(inside.items()):
            p = _pixel(grab, screen_w, x, y)
            assert not is_frame(p), (
                f"a frame colour is visible at {where} inside the region "
                f"{style}: {p} at ({x},{y})")

    # 2. The recording: not one of its pixels may be a frame colour. Everything
    #    within one band's width of each picture edge is scanned, the middle on a
    #    grid -- and the canvas grey must still dominate, so a capture of a dark
    #    desktop cannot pass for a clean one.
    video = manifest["video"]
    assert video.exists() and video.stat().st_size > 0, "the recording produced no MP4"
    stream = [s for s in _ffprobe_streams(video) if s.get("codec_type") == "video"][0]
    vw, vh = stream["width"], stream["height"]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video)], capture_output=True, text=True, check=True)
    seconds = float(json.loads(probe.stdout)["format"]["duration"])
    # Several moments, not one: a band that only strays across the captured area
    # for a third of a second, mid-gesture, is still in the file.
    times = [round(seconds * f, 2) for f in (0.15, 0.3, 0.45, 0.6, 0.7, 0.8, 0.9)]
    frame_raw = tmp_path / f"frame_{tag}.raw"
    inset = max(2, round((band + 2) * vw / region.w))
    offenders, sampled, canvas_pixels = [], 0, 0

    def scan(data, at, x, y):
        nonlocal sampled, canvas_pixels
        p = _pixel(data, vw, x, y)
        sampled += 1
        if is_frame(p):
            offenders.append((at, x, y, p))
        elif is_canvas(p):
            canvas_pixels += 1

    rows = []
    for y in range(vh):
        at_edge_row = y < inset or y >= vh - inset
        if at_edge_row:
            rows.append((y, range(0, vw, 2)))
        elif y % 16 == 0:
            rows.append((y, list(range(inset)) + list(range(inset, vw - inset, 16))
                         + list(range(vw - inset, vw))))
    for at in times:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(video),
             "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-y", str(frame_raw)],
            check=True, timeout=60,
        )
        data = _read_raw(frame_raw, vw, vh)
        for y, xs in rows:
            for x in xs:
                scan(data, at, x, y)

    assert not offenders, (
        f"{len(offenders)} recorded pixels carry the frame's own colours, as "
        f"(t, x, y, rgb) e.g. {offenders[:5]} -- the frame is being captured "
        f"(violates KTD2/AE4)")
    ratio = canvas_pixels / sampled
    assert ratio > 0.95, (
        f"only {canvas_pixels}/{sampled} sampled pixels ({ratio:.0%}) are the "
        f"canvas grey: the recording is not showing the selected region, so a "
        f"'no frame pixels' result would be vacuous")

    if drag:
        log = manifest.get("drag")
        assert log, "the host reported no refused drag, so this checked nothing"
        assert log["before"] == log["after"] == [region.x, region.y, region.w, region.h], (
            f"the refused gesture moved the region anyway: {log}")


def test_e2e_frame_pixels_absent_flush_region(tmp_path):
    """AE4 boundary case: a region tucked into the screen's top-left corner.

    Two of the four bands have nowhere to go and fall off screen; the two that
    do exist must stay out of the capture, and the top and left edges of the
    picture must not quietly turn into a band.
    """
    if not _has_env():
        pytest.skip("real capture e2e needs RUN_E2E=1, ffmpeg, and an X DISPLAY")
    _assert_frame_never_enters_the_capture(tmp_path, Region(0, 0, 1280, 720), "flush")


def test_e2e_frame_pixels_absent_interior_region(tmp_path):
    """Happy path: a region with room on all four sides, so all bands are drawn.

    This is the case the "+X+Y" grab offset got wrong: x11grab read the x offset,
    left y at 0, and the recording scooped up the region's own top band. Only
    reading the recorded pixels catches it.
    """
    if not _has_env():
        pytest.skip("real capture e2e needs RUN_E2E=1, ffmpeg, and an X DISPLAY")
    _assert_frame_never_enters_the_capture(tmp_path, Region(1200, 400, 1280, 720), "interior")


def test_e2e_frame_pixels_absent_while_a_drag_is_refused(tmp_path):
    """A drag attempted *during* recording must leave no trace in the file.

    Locking the region is not only about the end state: the bands must never
    travel across the captured area, not even between the press and the
    controller's refusal, because ffmpeg is sampling that area the whole time.
    """
    if not _has_env():
        pytest.skip("real capture e2e needs RUN_E2E=1, ffmpeg, and an X DISPLAY")
    _assert_frame_never_enters_the_capture(
        tmp_path, Region(1000, 300, 1280, 720), "refused_drag", drag=(150, 90))
