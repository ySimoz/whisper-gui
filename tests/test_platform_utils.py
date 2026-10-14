"""Unit tests for platform_utils cross-platform helpers."""

import sys
from pathlib import Path
from whisper_gui.platform_utils import (
    find_binary,
    get_subprocess_creation_flags,
    open_path_in_os,
    sanitize_filename,
)


def test_sanitize_filename():
    assert sanitize_filename("valid_name.wav") == "valid_name.wav"
    assert sanitize_filename("Lecture 10/12/2026: Physics?.mp3") == "Lecture 10_12_2026_ Physics_.mp3"
    assert sanitize_filename('test<file>"with|illegal*chars') == "test_file__with_illegal_chars"
    assert sanitize_filename("...dots...") == "dots"
    assert sanitize_filename("") == "transcript"


def test_find_binary():
    ffmpeg_path = find_binary("ffmpeg")
    assert ffmpeg_path is not None
    assert Path(ffmpeg_path).is_file()

    ffprobe_path = find_binary("ffprobe")
    assert ffprobe_path is not None
    assert Path(ffprobe_path).is_file()

    nonexistent = find_binary("nonexistent_binary_xyz_123")
    assert nonexistent is None


def test_get_subprocess_creation_flags():
    flags = get_subprocess_creation_flags()
    assert isinstance(flags, dict)
    if sys.platform.startswith("win"):
        assert "creationflags" in flags
    else:
        assert flags.get("start_new_session") is True


def test_open_path_nonexistent():
    assert open_path_in_os(Path("/path/that/does/not/exist/999")) is False


def test_reveal_file_in_os_nonexistent():
    from whisper_gui.platform_utils import reveal_file_in_os
    assert reveal_file_in_os(Path("/path/that/does/not/exist/999")) is False


def test_ensure_macos_environment(monkeypatch):
    import os
    from whisper_gui.platform_utils import ensure_macos_environment
    monkeypatch.setattr(sys, "platform", "darwin")
    ensure_macos_environment()
    # Should not raise exception
    assert isinstance(os.environ.get("PATH", ""), str)
