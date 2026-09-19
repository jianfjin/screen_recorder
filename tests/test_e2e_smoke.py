"""Real-capture end-to-end smoke test (U5).

Gated: only runs when RUN_E2E=1, ffmpeg is present, and an X DISPLAY is set.
It drives the actual encoder against the live X server (AE2/AE3) and the
no-audio variant (F2), then verifies the output with ffprobe.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

from app.aspect import Region
from app.encoder import Recorder, build_args


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
