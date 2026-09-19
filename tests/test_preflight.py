import subprocess
import app.preflight as pf
import pytest


def test_result_fields_and_can_launch():
    ok = pf.PreflightResult(ffmpeg=True, x11_display=True, audio_monitor=True)
    assert ok.can_launch() is True
    assert ok.missing() == []

    no_ff = pf.PreflightResult(ffmpeg=False, x11_display=True, audio_monitor=True)
    assert no_ff.can_launch() is False
    assert any("ffmpeg" in m for m in no_ff.missing())

    no_x = pf.PreflightResult(ffmpeg=True, x11_display=False, audio_monitor=True)
    assert no_x.can_launch() is False
    assert any("DISPLAY" in m for m in no_x.missing())

    no_audio = pf.PreflightResult(ffmpeg=True, x11_display=True, audio_monitor=False)
    # audio missing does NOT block launch (F2 handles it)
    assert no_audio.can_launch() is True
    assert any("audio" in m for m in no_audio.missing())


def test_check_ffmpeg(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    assert pf.check_ffmpeg() is True
    monkeypatch.setattr(pf.shutil, "which", lambda _: None)
    assert pf.check_ffmpeg() is False


def test_check_x11_display(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":1")
    assert pf.check_x11_display() is True
    monkeypatch.delenv("DISPLAY", raising=False)
    assert pf.check_x11_display() is False


def test_check_audio_monitor_true(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    class P:
        returncode = 0

    monkeypatch.setattr(pf.subprocess, "run", lambda *a, **k: P())
    assert pf.check_audio_monitor() is True


def test_check_audio_monitor_false_on_error(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda _: "/usr/bin/ffmpeg")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ffmpeg", 6)

    import subprocess  # noqa: F401
    monkeypatch.setattr(pf.subprocess, "run", boom)
    assert pf.check_audio_monitor() is False


def test_check_audio_monitor_false_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(pf.shutil, "which", lambda _: None)
    assert pf.check_audio_monitor() is False


def test_run_preflight_aggregates(monkeypatch):
    monkeypatch.setattr(pf, "check_ffmpeg", lambda: True)
    monkeypatch.setattr(pf, "check_x11_display", lambda: False)
    monkeypatch.setattr(pf, "check_audio_monitor", lambda: True)
    r = pf.run_preflight()
    assert r == pf.PreflightResult(True, False, True)


def test_describe_lists_gaps():
    r = pf.PreflightResult(False, False, False)
    text = pf.describe(r)
    assert "ffmpeg" in text and "DISPLAY" in text and "audio" in text
    assert pf.describe(pf.PreflightResult(True, True, True)) == "All checks passed."
