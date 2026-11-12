"""Tests for auto-update version checking, asset download/extraction, and UpdateDialog."""

from __future__ import annotations

import io
import json
import os
import tarfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whisper_gui.ui.update_dialog import UpdateDialog
from whisper_gui.updater import (
    ReleaseInfo,
    apply_update_and_relaunch,
    download_release_asset,
    extract_release_archive,
    fetch_latest_release,
    get_install_target,
    is_newer_version,
    parse_version,
    select_asset_for_platform,
)


def test_version_parsing_and_comparison():
    assert parse_version("v0.2.1") == ((0, 2, 1), "")
    assert parse_version("0.2.0-rc1") == ((0, 2, 0), "rc1")
    assert parse_version("latest-build") is None

    assert is_newer_version("v0.2.0", "0.1.0") is True
    assert is_newer_version("v0.1.0", "0.1.0") is False
    assert is_newer_version("v0.0.9", "0.1.0") is False
    assert is_newer_version("v0.2.0", "0.2.0-rc1") is True
    assert is_newer_version("latest-build", "0.1.0") is False


def test_select_asset_for_platform():
    assets = [
        {"name": "WhisperGUI-linux-x86_64.tar.gz", "browser_download_url": "https://example.com/linux.tar.gz"},
        {"name": "WhisperGUI-macos.zip", "browser_download_url": "https://example.com/macos.zip"},
        {"name": "WhisperGUI-windows-x64.zip", "browser_download_url": "https://example.com/win.zip"},
    ]
    assert select_asset_for_platform(assets, "darwin")["name"] == "WhisperGUI-macos.zip"
    assert select_asset_for_platform(assets, "win32")["name"] == "WhisperGUI-windows-x64.zip"
    assert select_asset_for_platform(assets, "linux")["name"] == "WhisperGUI-linux-x86_64.tar.gz"


def test_fetch_latest_release_success_and_offline():
    payload = {
        "tag_name": "v0.2.0",
        "body": "### Highlights\n- Added auto-updater",
        "html_url": "https://github.com/ySimoz/whisper-gui/releases/tag/v0.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "WhisperGUI-macos.zip",
                "browser_download_url": "https://github.com/ySimoz/whisper-gui/releases/download/v0.2.0/WhisperGUI-macos.zip",
                "size": 12345,
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        info = fetch_latest_release("0.1.0", platform_name="darwin")
    assert info is not None
    assert info.version == "0.2.0"
    assert "Added auto-updater" in info.changelog
    assert info.asset_name == "WhisperGUI-macos.zip"

    # Same version returns None
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert fetch_latest_release("0.2.0", platform_name="darwin") is None

    # Offline / network failure returns None gracefully
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
        assert fetch_latest_release("0.1.0", platform_name="darwin") is None


def test_download_release_asset_and_cancellation(tmp_path):
    dest = tmp_path / "update.zip"

    with pytest.raises(ValueError, match="HTTPS"):
        download_release_asset("http://insecure.example.com/app.zip", dest)

    class FakeResp:
        headers = {"Content-Length": "10"}

        def __init__(self, chunks):
            self._chunks = list(chunks)

        def read(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    progress_calls = []
    with patch("urllib.request.urlopen", return_value=FakeResp([b"hello", b"world"])):
        out = download_release_asset(
            "https://example.com/app.zip",
            dest,
            progress_cb=lambda done, total: progress_calls.append((done, total)),
        )
    assert out.read_bytes() == b"helloworld"
    assert progress_calls == [(5, 10), (10, 10)]

    # Cancelled download removes .part file
    dest2 = tmp_path / "cancelled.zip"
    with patch("urllib.request.urlopen", return_value=FakeResp([b"hello", b"world"])):
        with pytest.raises(InterruptedError):
            download_release_asset(
                "https://example.com/app.zip",
                dest2,
                cancel_check=lambda: True,
            )
    assert not dest2.exists()
    assert not (tmp_path / "cancelled.zip.part").exists()


def test_extract_release_archive_macos_linux_windows(tmp_path):
    # macOS .app inside zip
    mac_zip = tmp_path / "WhisperGUI-macos.zip"
    with zipfile.ZipFile(mac_zip, "w") as zf:
        zf.writestr("WhisperGUI.app/Contents/MacOS/WhisperGUI", "#!/bin/sh\n")
    extracted_mac = extract_release_archive(mac_zip, tmp_path / "out_mac", platform_name="darwin")
    assert extracted_mac.name == "WhisperGUI.app"

    # Linux .tar.gz
    lin_tgz = tmp_path / "WhisperGUI-linux-x86_64.tar.gz"
    with tarfile.open(lin_tgz, "w:gz") as tf:
        data = b"#!/bin/sh\n"
        ti = tarfile.TarInfo("WhisperGUI/WhisperGUI")
        ti.size = len(data)
        ti.mode = 0o755
        tf.addfile(ti, io.BytesIO(data))
    extracted_lin = extract_release_archive(lin_tgz, tmp_path / "out_lin", platform_name="linux")
    assert extracted_lin.name == "WhisperGUI"
    assert (extracted_lin / "WhisperGUI").is_file()

    # Windows .zip
    win_zip = tmp_path / "WhisperGUI-windows-x64.zip"
    with zipfile.ZipFile(win_zip, "w") as zf:
        zf.writestr("WhisperGUI/WhisperGUI.exe", "MZ")
    extracted_win = extract_release_archive(win_zip, tmp_path / "out_win", platform_name="win32")
    assert (extracted_win / "WhisperGUI.exe").is_file()

    # Zip-slip traversal rejected
    bad_zip = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("../evil.txt", "nope")
    with pytest.raises(ValueError, match="Unsafe archive"):
        extract_release_archive(bad_zip, tmp_path / "out_bad", platform_name="win32")


def test_get_install_target_and_apply_update(tmp_path):
    mac_exe = tmp_path / "WhisperGUI.app" / "Contents" / "MacOS" / "WhisperGUI"
    mac_exe.parent.mkdir(parents=True)
    mac_exe.write_text("")
    assert get_install_target(mac_exe, platform_name="darwin") == tmp_path / "WhisperGUI.app"

    new_app = tmp_path / "new" / "WhisperGUI.app"
    new_app.mkdir(parents=True)
    target_app = tmp_path / "WhisperGUI.app"

    with patch("whisper_gui.updater.subprocess.Popen") as mock_popen:
        apply_update_and_relaunch(new_app, target_app, current_pid=999999, platform_name="darwin")
    assert mock_popen.called

    with patch("whisper_gui.updater.is_writable_target", return_value=False):
        with pytest.raises(PermissionError):
            apply_update_and_relaunch(new_app, target_app, current_pid=999999, platform_name="darwin")


def test_update_dialog_ui(qtbot):
    release = ReleaseInfo(
        version="0.2.0",
        tag_name="v0.2.0",
        changelog="### Highlights\n- Faster transcription\n- Auto-update prompt",
        html_url="https://github.com/ySimoz/whisper-gui/releases/tag/v0.2.0",
        asset_name="WhisperGUI-macos.zip",
        download_url="https://github.com/ySimoz/whisper-gui/releases/download/v0.2.0/WhisperGUI-macos.zip",
        asset_size=1024,
    )

    # Unbundled (source) mode -> Download on GitHub
    with patch("whisper_gui.ui.update_dialog.is_bundled", return_value=False):
        dlg_src = UpdateDialog(release)
        qtbot.addWidget(dlg_src)
        assert dlg_src.btn_update.text() == "Download on GitHub"
        assert "Faster transcription" in dlg_src.txt_changelog.toPlainText()
        dlg_src.btn_cancel.click()
        assert dlg_src.result() == UpdateDialog.Rejected

    # Bundled mode -> Update Now + progress + relaunch_ready quits app
    with patch("whisper_gui.ui.update_dialog.is_bundled", return_value=True):
        dlg_bin = UpdateDialog(release)
        qtbot.addWidget(dlg_bin)
        assert dlg_bin.btn_update.text() == "Update Now"
        dlg_bin._on_progress(50, 100)
        assert dlg_bin.progress_bar.value() == 50

        with patch("whisper_gui.ui.update_dialog.QApplication.instance") as mock_app:
            dlg_bin._on_relaunch_ready()
            assert mock_app.return_value.quit.called
