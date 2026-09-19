"""Startup environment checks (KTD8).

Each check returns a plain bool so the entry point can decide whether to
launch, warn, or exit with a clear message. Nothing here raises for a
missing dependency.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightResult:
    ffmpeg: bool
    x11_display: bool
    audio_monitor: bool

    def can_launch(self) -> bool:
        """Hard requirements to even open the app (audio is soft, handled by F2)."""
        return self.ffmpeg and self.x11_display

    def missing(self) -> list[str]:
        items: list[str] = []
        if not self.ffmpeg:
            items.append("ffmpeg not found on PATH")
        if not self.x11_display:
            items.append("no X11 DISPLAY (run inside an Xorg session)")
        if not self.audio_monitor:
            items.append("no system audio monitor source (recordings may be silent)")
        return items


def check_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def check_x11_display() -> bool:
    return bool(os.environ.get("DISPLAY"))


def check_audio_monitor(timeout: float = 6.0) -> bool:
    """Probe whether ffmpeg can read the Pulse/PipeWire default monitor source.

    Runs a very short null-encode against ``@DEFAULT_MONITOR`` and treats a
    clean exit as "available". Returns False on any error or timeout.
    """
    if shutil.which("ffmpeg") is None:
        return False
    probe = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "pulse", "-i", "@DEFAULT_MONITOR",
        "-t", "0.2", "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(
            probe,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def run_preflight() -> PreflightResult:
    return PreflightResult(
        ffmpeg=check_ffmpeg(),
        x11_display=check_x11_display(),
        audio_monitor=check_audio_monitor(),
    )


def describe(result: PreflightResult) -> str:
    """Human-readable summary used for launch-time warnings/errors."""
    missing = result.missing()
    if not missing:
        return "All checks passed."
    return "Missing:\n  - " + "\n  - ".join(missing)
