import datetime
import os
from pathlib import Path

import pytest

from app.aspect import Region
from app.encoder import build_args, make_output_path


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
    assert ":0.0+5+8" in a
    assert "800x450" in a


def test_unsupported_aspect_raises():
    with pytest.raises(ValueError):
        _a(Region(0, 0, 640, 360), "4:3")


def test_make_output_path_pattern(tmp_path):
    when = datetime.datetime(2026, 7, 11, 12, 34, 56)
    p = make_output_path(when=when, base_dir=tmp_path)
    assert p.name == "screen_20260711-123456.mp4"
    assert p.parent == tmp_path
    assert p.parent.exists()
