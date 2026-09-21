"""Live-X host for the frame-contamination checks in test_e2e_smoke.py.

Run as a subprocess, never imported by a test: the pytest process already owns
an *offscreen* QApplication (tests/conftest.py) and Qt allows one application
per process, so putting a real window on a real display needs its own process.

It does, in the order the checks depend on:
  1. maps a solid mid-gray canvas exactly over the capture region, so "clean"
     has a known value and a canvas that never appeared cannot read as clean;
  2. shows the real ``MainWindow``, with the real ``RegionFrame`` around the
     same region, then grabs the whole screen -- the proof that the frame is
     actually painted on the desktop, outside the region. ``--window-mode away``
     parks the window clear of both, which is how a user who leaves it alone
     records; ``--window-mode over`` parks it on the region's centre instead,
     and is the only way to watch the interface get out of the way (R1, AE1);
  3. starts a real recording through ``MainWindow``'s own seam -- not the
     controller's, which is the path the app no longer takes -- grabs the screen
     once more in the recording style, and stops.

It asserts nothing; the caller inspects the two grabs and the MP4.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest                        # noqa: E402
from PySide6.QtGui import QColor, QPainter                   # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget          # noqa: E402

from app.aspect import Region                                # noqa: E402
from app.controller import RecordingController               # noqa: E402
from app.encoder import Recorder, build_args                 # noqa: E402
from app.frame import RegionFrame                            # noqa: E402
from app.mainwindow import MainWindow                        # noqa: E402
from app.strip import BACKGROUND_COLOR, TEXT_COLOR           # noqa: E402
from app.strip import should_collapse, strip_placement          # noqa: E402

CANVAS_GRAY = QColor(128, 128, 128)
WINDOW_SIZE = (600, 190)          # MainWindow.setFixedSize in app/mainwindow.py
IDLE_GRAB_MS = 800
START_MS = 1300
RECORDING_GRAB_MS = 2000
STOP_MS = 4400
QUIT_MS = 5100
RESTORED_GRAB_MS = 4800   # after the stop, before the teardown


def _as_list(region):
    return [region.x, region.y, region.w, region.h]


class _Canvas(QWidget):
    """The recorded content: one flat gray rectangle over the region."""

    def __init__(self, region: Region, managed: bool = False):
        super().__init__()
        # The flags the frame itself uses: the canvas must land on exactly the
        # pixels under test, with no window-manager decoration or stacking
        # surprise shifting them.
        # `managed` is for the mode that parks the app window on top of the
        # region: an override-redirect canvas cannot be passed by raising a
        # normal window, so the window under test would hide behind the content
        # and a clean recording would prove nothing at all. A frameless managed
        # canvas still covers exactly the region, which the host re-checks.
        flags = Qt.FramelessWindowHint
        if not managed:
            flags |= (Qt.WindowStaysOnTopHint
                      | Qt.X11BypassWindowManagerHint)
        self.setWindowFlags(flags)
        # A managed window shown with it never maps on this session, so only the
        # override-redirect one asks not to be activated.
        if not managed:
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(region.x, region.y, region.w, region.h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), CANVAS_GRAY)
        painter.end()


def _park_main_window_away_from(screen_w: int, screen_h: int, region: Region,
                               band: int) -> tuple:
    """Top-left for the control window where it touches neither region nor bands."""
    blocked = (region.x - band, region.y - band - 40,
               region.w + 2 * band, region.h + 2 * band + 40)
    candidates = [
        (screen_w - WINDOW_SIZE[0] - 10, screen_h - WINDOW_SIZE[1] - 10),
        (screen_w - WINDOW_SIZE[0] - 10, 10),
        (10, screen_h - WINDOW_SIZE[1] - 10),
        (max(0, region.x + region.w + 3 * band), max(0, region.y + region.h + 3 * band)),
    ]
    for x, y in candidates:
        if not (x < blocked[0] + blocked[2] and x + WINDOW_SIZE[0] > blocked[0]
                and y < blocked[1] + blocked[3] and y + WINDOW_SIZE[1] > blocked[1]):
            return x, y
    return candidates[-1]


def _rgb(hex_colour: str):
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _pixel_of(path: Path, width: int, x: int, y: int):
    with path.open("rb") as handle:
        handle.seek((y * width + x) * 3)
        raw = handle.read(3)
    return tuple(raw)


def _grab_screen(display: str, w: int, h: int, dest: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "x11grab", "-video_size", f"{w}x{h}", "-draw_mouse", "0",
         "-i", f"{display}.0", "-frames:v", "1",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-y", str(dest)],
        check=True, timeout=30,
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, help="x,y,w,h")
    ap.add_argument("--out", required=True, help="where to write the MP4")
    ap.add_argument("--art-dir", required=True, help="where to write the grabs")
    ap.add_argument("--display", default=os.environ.get("DISPLAY", ":0"))
    ap.add_argument("--drag-while-recording", default="",
                    help="dx,dy to attempt mid-recording, a gesture the "
                         "controller is supposed to refuse")
    ap.add_argument("--window-mode", default="away", choices=("away", "over"),
                    help="'away' parks the control window clear of the region, as "
                         "someone who leaves it alone does; 'over' parks it on the "
                         "region centre, which is the case that has to collapse the "
                         "interface out of the shot")
    args = ap.parse_args(argv)

    x, y, w, h = (int(v) for v in args.region.split(","))
    region = Region(x, y, w, h)
    out = Path(args.out)
    art = Path(args.art_dir)
    art.mkdir(parents=True, exist_ok=True)
    idle_grab = art / "screen_idle.raw"
    recording_grab = art / "screen_recording.raw"
    restored_grab = art / "screen_restored.raw"
    if out.exists():
        out.unlink()

    app = QApplication(["e2e-frame-host"])
    screen = QApplication.primaryScreen().geometry()
    room = RegionFrame.BAND + 2
    if screen.width() < x + w + room or screen.height() < y + h + room:
        print(f"display {screen.width()}x{screen.height()} has no room for region "
              f"{x},{y},{w},{h} plus its frame bands", file=sys.stderr)
        return 2

    offsets = ([int(v) for v in args.drag_while_recording.split(",")]
               if args.drag_while_recording else None)
    drag_log = {}

    canvas = _Canvas(region, managed=(args.window_mode == "over"))
    canvas.show()
    canvas.raise_()

    def make_recorder(r, aspect, out_path, with_audio, display=None):
        return Recorder(build_args(r, aspect, out_path, with_audio=with_audio,
                                   display=args.display))

    # The audio probe gets a fixed answer so the run can never end up inside the
    # "continue silently?" dialog; the encoder path itself is the production one.
    controller = RecordingController(make_recorder=make_recorder,
                                     audio_available=lambda: True,
                                     make_path=lambda base_dir=None: out)
    window = MainWindow(controller)
    window.show()
    if args.window_mode == "over":
        # On top of the pixels about to be captured, and raised above the
        # canvas -- which in this mode is a managed window precisely so that a
        # raise means something. Otherwise the recording would be clean whether
        # or not the interface ever moved, and the pixel premise below is the
        # check that catches that.
        window.move(region.x + region.w // 2 - WINDOW_SIZE[0] // 2,
                    region.y + region.h // 2 - WINDOW_SIZE[1] // 2)
        window.raise_()
    else:
        window.move(*_park_main_window_away_from(screen.width(), screen.height(),
                                                 region, RegionFrame.BAND))
    window_rect = window.frameGeometry().getRect()
    origin = window.mapToGlobal(QPoint(0, 0))   # the pixels the user sees, not the
    window_pos = (origin.x(), origin.y())   # frame a WM may only report after map
    controller.selection_finished(region)   # -> region_ready -> frame shows

    def grab(name):
        _grab_screen(args.display, screen.width(), screen.height(), name)
        if name == idle_grab:
            _confirm_paint(name)
        if name == restored_grab:
            log_after_stop["window_mapped"] = window.isVisible()
            here = window.mapToGlobal(QPoint(0, 0))
            log_after_stop["window_pos"] = (here.x(), here.y())

    def _confirm_paint(path: Path) -> None:
        """Bail out (exit 2 -> the caller skips) when the display shows none of this.

        A blanked or locked session keeps a root window that reads as flat
        black, so both the bands and the canvas would be missing and every
        pixel check downstream would be meaningless -- and would look like a
        failure of the frame rather than of the session.
        """
        probe_x, probe_y = _canvas_probe_point()
        seen = _pixel_of(path, screen.width(), probe_x, probe_y)
        if max(abs(a - b) for a, b in zip(seen, (CANVAS_GRAY.red(),
                                                 CANVAS_GRAY.green(),
                                                 CANVAS_GRAY.blue()))) > 45:
            fail(
                f"the display is not showing what this process painted (canvas "
                f"grey expected at ({probe_x}, {probe_y}), found {seen}). The session "
                f"looks blanked or locked: check `xset q` DPMS state and "
                f"`loginctl show-session <id> -p LockedHint`, wake the desktop, "
                f"and run again.")

    def _canvas_probe_point():
        """A pixel of the region that the parked window is not sitting on.

        This check exists to prove the display shows what this process painted.
        In 'over' mode the window covers the region's centre, the one point it
        used to read, so the bail-out would have been about the window rather
        than about a session that never painted anything at all.
        """
        parked = QRect(*window_rect)
        candidates = [(region.x + region.w // 2, region.y + region.h // 2),
                      (region.x + region.w - 8, region.y + 8),
                      (region.x + 8, region.y + region.h - 8),
                      (region.x + region.w - 8, region.y + region.h - 8)]
        for px, py in candidates:
            if not parked.contains(QRect(px, py, 1, 1)):
                return px, py
        return candidates[0]

    log_after_stop = {}
    bailed = []

    def attempt_drag():
        """Refused-by-design gesture straight across the live capture, in steps.

        The transient positions are the point: x11grab samples at 30fps, so if
        the bands ever travel over the captured area, the finished file shows it.
        Driving the frame's drag seam is the same call sequence a real press on a
        band makes; routing the physical pointer is the manual row of the plan.
        """
        frame = window._frame
        before = frame.region()
        x0, y0 = before.x + before.w // 2, before.y - 1
        frame.begin_drag(x0, y0)
        for step in range(1, 9):
            frame.update_drag(x0 + offsets[0] * step // 8, y0 + offsets[1] * step // 8)
            # Real pacing: a hand drags for a quarter of a second, and x11grab
            # samples every 33ms. Blinking through the steps in a millisecond
            # would let a displaced band dodge the capture entirely, and the
            # check would pass without proving anything.
            QTest.qWait(45)
        frame.end_drag(x0 + offsets[0], y0 + offsets[1])
        QTest.qWait(120)
        after = frame.region()
        drag_log.update(before=_as_list(before), after=_as_list(after),
                        dx=offsets[0], dy=offsets[1])

    def fail(message: str) -> None:
        print(message, file=sys.stderr)
        bailed.append(message)
        app.quit()

    controller.error.connect(lambda msg: fail(f"recording failed: {msg}"))
    QTimer.singleShot(IDLE_GRAB_MS, lambda: grab(idle_grab))
    QTimer.singleShot(START_MS, window._start_recording)
    QTimer.singleShot(RECORDING_GRAB_MS, lambda: grab(recording_grab))
    if offsets:
        QTimer.singleShot(RECORDING_GRAB_MS + 500, attempt_drag)
    # Stop through whichever button this run's user would have found: collapsed,
    # the strip's is the only one there is, and R10 promises the two are one path.
    def stop_the_recording():
        if window._strip.is_visible():
            log_after_stop["stop_via"] = "strip"
            window._strip._stop_btn.click()
        else:
            log_after_stop["stop_via"] = "window"
            window._stop_recording()

    QTimer.singleShot(STOP_MS, stop_the_recording)
    QTimer.singleShot(RESTORED_GRAB_MS, lambda: grab(restored_grab))
    QTimer.singleShot(QUIT_MS, app.quit)
    app.exec()

    if bailed:
        return 2                      # caller skips: the session, not the code
    if not out.exists():
        fail("no MP4 was produced")
        return 1
    (art / "manifest.json").write_text(json.dumps({
        "screen": [screen.width(), screen.height()],
        "region": [x, y, w, h],
        "gray": [CANVAS_GRAY.red(), CANVAS_GRAY.green(), CANVAS_GRAY.blue()],
        "idle_color": RegionFrame.IDLE_COLOR,
        "recording_color": RegionFrame.RECORDING_COLOR,
        "band": RegionFrame.BAND,
        "video": str(out),
        "grabs": {"idle": str(idle_grab), "recording": str(recording_grab),
                  "restored": str(restored_grab)},
        "drag": drag_log,
        "window_pos": list(window_pos),
        "window_rect": list(window_rect),
        "collapse_expected": should_collapse(window_rect, region),
        "strip_colors": [_rgb(BACKGROUND_COLOR), _rgb(TEXT_COLOR)],
        "strip_inside": strip_placement(region, screen.width(), screen.height())[3],
        "strip_rect": list(strip_placement(region, screen.width(), screen.height())[0]),
        "after_stop": log_after_stop,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
