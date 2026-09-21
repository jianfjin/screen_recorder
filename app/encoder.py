"""ffmpeg argument construction, output-path naming, and recorder process mgmt.

KTD2: the GUI never decodes frames; it builds one ffmpeg command (x11grab +
pulse monitor -> libx264/AAC -> MP4) and manages the subprocess. KTD3 (no
cursor), KTD4 (pulse monitor), KTD5 (1080p scale), KTD6 (output path),
KTD7 (encode defaults) all land as argument choices here.
"""
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .aspect import Region, TARGETS

DEFAULT_FPS = 30


def make_output_path(when: datetime | None = None,
                     base_dir: str | os.PathLike | None = None) -> Path:
    """KTD6: ~/Videos/screen_YYYYmmdd-HHMMSS.mp4, creating the dir if needed."""
    when = when or datetime.now()
    base = Path(base_dir) if base_dir is not None else Path.home() / "Videos"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"screen_{when:%Y%m%d-%H%M%S}.mp4"
    # Guard against same-second collisions overwriting a previous recording
    # (build_args passes -y, which would silently clobber an existing file).
    n = 1
    while path.exists():
        path = base / f"screen_{when:%Y%m%d-%H%M%S}-{n}.mp4"
        n += 1
    return path


def build_args(region: Region, aspect: str, out_path: str | os.PathLike,
               with_audio: bool = True,
               display: str | None = None) -> list[str]:
    """Return the ffmpeg argv (without the program) for one recording.

    `with_audio=False` yields the "continue-silent" variant (F2): the pulse
    monitor input and the AAC encoder are both omitted.
    """
    if aspect not in TARGETS:
        raise ValueError(f"unsupported aspect {aspect!r}; expected one of {sorted(TARGETS)}")
    target_w, target_h = TARGETS[aspect]
    display = display if display is not None else os.environ.get("DISPLAY", ":0")
    out = Path(out_path).expanduser()
    # x11grab capture size must be even for the yuv420p libx264 path; the
    # final size is fixed by the scale filter, so flooring is lossless in practice.
    cap_w = region.w if region.w % 2 == 0 else region.w - 1
    cap_h = region.h if region.h % 2 == 0 else region.h - 1

    args = [
        "-hide_banner", "-loglevel", "error",
        # Video: x11grab the selected region, no on-screen cursor (KTD3).
        "-f", "x11grab",
        "-draw_mouse", "0",
        "-framerate", str(DEFAULT_FPS),          # KTD7
        "-video_size", f"{cap_w}x{cap_h}",
        # The grab offset goes in as options, not in the filename: x11grab
        # parses "+X+Y" as X then a comma-separated Y, so the second "+" leaves
        # the vertical offset at 0 and every recording comes from the top of the
        # screen. Verified against the live X server (U4 frame check).
        "-grab_x", str(region.x),
        "-grab_y", str(region.y),
        "-i", f"{display}.0",
    ]
    if with_audio:
        # System audio via the Pulse/PipeWire default monitor (KTD4).
        args += ["-f", "pulse", "-i", "@DEFAULT_MONITOR"]
    # Scale the (aspect-locked) region to the fixed 1080p target (KTD5).
    args += [
        "-vf", f"scale={target_w}:{target_h}",
        "-c:v", "libx264",                        # KTD7
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
    ]
    if with_audio:
        args += ["-c:a", "aac", "-b:a", "192k"]   # KTD7
    args += ["-movflags", "+faststart"]           # KTD7
    args += ["-y", str(out)]
    return args


class Recorder:
    """Owns the ffmpeg subprocess.

    stop() shuts ffmpeg down gracefully (stdin 'q', then SIGINT, then kill)
    so the MP4 moov atom is finalized; a hard kill leaves an unplayable file.
    """

    def __init__(self, args: list[str], program: str = "ffmpeg"):
        self._args = list(args)
        self._program = program
        self._proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> subprocess.Popen:
        if self.running:
            raise RuntimeError("recorder already running")
        self._proc = subprocess.Popen(
            [self._program, *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return self._proc

    def stop(self, timeout: float = 5.0) -> int | None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return None
        if proc.poll() is None:
            self._send(proc, "q")
            self._wait(proc, timeout)
            if proc.poll() is None:
                self._signal(proc, signal.SIGINT)
                self._wait(proc, timeout)
            if proc.poll() is None:
                proc.kill()
        try:
            # The reaping wait has to be bounded like the two above it: stop()
            # runs on the GUI thread, and a child that cannot be reaped -- stuck
            # in kernel I/O, or blocked writing to a stderr pipe nobody drains --
            # would otherwise freeze the whole interface right here, with no
            # repaint, no button answering and no window coming back. Returning
            # None says what is true: the file is whatever ffmpeg got to, and the
            # exit code is unknown.
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    @staticmethod
    def _send(proc: subprocess.Popen, text: str) -> None:
        try:
            if proc.stdin is not None:
                proc.stdin.write(text.encode())
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    @staticmethod
    def _signal(proc: subprocess.Popen, sig: int) -> None:
        try:
            proc.send_signal(sig)
        except (ProcessLookupError, OSError):
            pass

    @staticmethod
    def _wait(proc: subprocess.Popen, timeout: float) -> None:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
