"""U2 (R3 / AE3): user can choose the save directory; default is ~/Videos."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from app.controller import RecordingController
from app.mainwindow import MainWindow


class _Recorder:
    def start(self):
        pass

    def stop(self):
        pass

    @property
    def running(self):
        return False


def _win(qapp):
    controller = RecordingController(
        make_recorder=lambda *a, **k: _Recorder(),
        audio_available=lambda: True,
        make_path=lambda base_dir=None: "/tmp/x.mp4",
    )
    return MainWindow(controller), controller


def test_default_save_dir_label_shows_home_videos(qapp):
    win, _ = _win(qapp)
    assert str(Path.home() / "Videos") in win._save_dir_label.text()


def test_set_save_dir_updates_controller_and_label(qapp, tmp_path):
    win, c = _win(qapp)
    win._set_save_dir(str(tmp_path))
    assert c.save_dir == tmp_path
    assert str(tmp_path) in win._save_dir_label.text()


def test_set_save_dir_none_resets_to_default(qapp):
    win, c = _win(qapp)
    win._set_save_dir("/tmp/xyz")
    assert c.save_dir == Path("/tmp/xyz")
    win._set_save_dir("")  # empty => reset to default
    assert c.save_dir is None
    assert str(Path.home() / "Videos") in win._save_dir_label.text()
