import datetime
import os
import subprocess
from pathlib import Path

import pytest

from app.aspect import Region
from app.encoder import Recorder, build_args, make_output_path


def _a(region, aspect, with_audio=True, display=":1", out="/tmp/o.mp4"):
    return build_args(region, aspect, out, with_audio=with_audio, display=display)


def test_16_9_with_audio_full_args():
    a = _a(Region(0, 0, 1280, 720), "16:9", with_audio=True)
    s = a
    assert "scale=1920:1080" in s
    assert "0" in s[s.index("-draw_mouse") + 1:] or "-draw_mouse 0".replace(" ", " ")
    assert s[s.index("-draw_mouse") + 1] == "0"
    assert "@DEFAULT_MONITOR" in s
    assert "libx264" in s and "aac" in s
    assert "-movflags" in s and "+faststart" in s
    assert s[-1] == "/tmp/o.mp4"


def test_3_2_scales_to_1620x1080():
    a = _a(Region(10, 20, 1080, 720), "3:2", with_audio=True)
    assert "scale=1620:1080" in a


def test_no_audio_omits_pulse_and_aac():
    a = _a(Region(0, 0, 640, 360), "16:9", with_audio=False)
    assert "@DEFAULT_MONITOR" not in a
    assert "aac" not in a
    assert "libx264" in a  # video still present


def test_region_maps_to_geometry_and_size():
    a = _a(Region(5, 8, 800, 450), "16:9", display=":0")
    assert ":0.0" in a
    assert "800x450" in a
    assert a[a.index("-grab_x") + 1] == "5"
    assert a[a.index("-grab_y") + 1] == "8"


def test_grab_offset_never_travels_in_the_filename():
    """Regression: "+X+Y" is mis-parsed as X with a comma-separated Y.

    ffmpeg read the x offset and silently left y at 0, so a region below the
    top of the screen recorded the wrong strip of the desktop. The offsets must
    be options, and the input must stay a bare ":display.screen".
    """
    a = _a(Region(1200, 400, 1280, 720), "16:9", display=":1")
    assert a[a.index("-i") + 1] == ":1.0", "no offset suffix in the input literal"
    assert not any(tok.startswith(":") and "+" in tok for tok in a), a
    assert a[a.index("-grab_x") + 1] == "1200"
    assert a[a.index("-grab_y") + 1] == "400"
    # -grab_y is not the global overwrite flag; keep both distinguishable.
    assert a.count("-y") == 1 and a[-2] == "-y"


def test_unsupported_aspect_raises():
    with pytest.raises(ValueError):
        _a(Region(0, 0, 640, 360), "4:3")


def test_make_output_path_pattern(tmp_path):
    when = datetime.datetime(2026, 7, 11, 12, 34, 56)
    p = make_output_path(when=when, base_dir=tmp_path)
    assert p.name == "screen_20260711-123456.mp4"
    assert p.parent == tmp_path
    assert p.parent.exists()


def test_make_output_path_avoids_same_second_collision(tmp_path):
    # Model the real flow: each recording's file is on disk before the next
    # name is reserved, so a same-second re-record must not clobber it.
    when = datetime.datetime(2026, 7, 11, 12, 34, 56)
    p1 = make_output_path(when=when, base_dir=tmp_path)
    p1.write_bytes(b"x")
    p2 = make_output_path(when=when, base_dir=tmp_path)
    p2.write_bytes(b"x")
    p3 = make_output_path(when=when, base_dir=tmp_path)
    assert p1.name == "screen_20260711-123456.mp4"
    assert p2.name == "screen_20260711-123456-1.mp4"
    assert p3.name == "screen_20260711-123456-2.mp4"
    assert len({p1, p2, p3}) == 3


def test_make_output_path_defaults_to_home_videos(tmp_path, monkeypatch):
    from pathlib import Path as _P
    monkeypatch.setattr(_P, "home", staticmethod(lambda: tmp_path))
    from app.encoder import make_output_path as f
    p = f(when=datetime.datetime(2026, 7, 11, 12, 34, 56))
    assert p.parent == tmp_path / "Videos"
    assert p.parent.exists()


class _StubbornProcess:
    # A child that will not be reaped: poll() never sees an exit, and an
    # untimed wait() blocks forever. That is the shape of an ffmpeg stuck in
    # kernel I/O or blocked on an unread stderr pipe.
    returncode = None

    def __init__(self):
        self.signals = []
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        if timeout is None:
            raise _WouldBlockForever()
        raise subprocess.TimeoutExpired("ffmpeg", timeout)

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.killed = True

    stdin = None


class _WouldBlockForever(Exception):
    pass


def test_stop_never_waits_on_a_child_that_cannot_be_reaped(tmp_path):
    # stop() runs on the GUI thread, so an unbounded wait here is the whole
    # interface hanging: no repaint, no button answering, no window coming back.
    rec = Recorder(["-i", "x"])
    proc = _StubbornProcess()
    rec._proc = proc

    result = rec.stop(timeout=0.01)

    assert proc.killed is True, "the escalation to kill must still happen"
    assert result is None, "an unreapable child must report no exit code, not block"
