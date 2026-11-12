"""Unit tests for OS-native API key storage and migration in credentials.py."""

from __future__ import annotations

import base64
import ctypes
import subprocess
import sys
from unittest.mock import MagicMock

from PySide6.QtCore import QSettings

from whisper_gui import credentials


def _make_settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "creds.ini"), QSettings.IniFormat)


def test_darwin_store_load_delete_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    settings = _make_settings(tmp_path)
    keychain: dict[tuple[str, str], str] = {}

    def fake_run(cmd, **_kwargs):
        action = cmd[1]
        if action == "add-generic-password":
            svc = cmd[cmd.index("-s") + 1]
            acc = cmd[cmd.index("-a") + 1]
            pw = cmd[cmd.index("-w") + 1]
            keychain[(svc, acc)] = pw
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if action == "find-generic-password":
            svc = cmd[cmd.index("-s") + 1]
            acc = cmd[cmd.index("-a") + 1]
            if (svc, acc) in keychain:
                return subprocess.CompletedProcess(cmd, 0, stdout=keychain[(svc, acc)] + "\n", stderr="")
            return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")
        if action == "delete-generic-password":
            svc = cmd[cmd.index("-s") + 1]
            acc = cmd[cmd.index("-a") + 1]
            keychain.pop((svc, acc), None)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(credentials.subprocess, "run", fake_run)

    # Store -> keychain used, plain-text removed
    settings.setValue(credentials.QSETTINGS_PLAIN_KEY, "old-plain")
    credentials.store_api_key("sk-mac-secret", settings)
    assert keychain[(credentials.SERVICE_NAME, credentials.ACCOUNT_NAME)] == "sk-mac-secret"
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""
    assert credentials.load_api_key(settings) == "sk-mac-secret"

    # Delete -> removed from keychain and QSettings
    credentials.delete_api_key(settings)
    assert (credentials.SERVICE_NAME, credentials.ACCOUNT_NAME) not in keychain
    assert credentials.load_api_key(settings) == ""

    # Fallback when security CLI fails
    def fail_run(*_args, **_kwargs):
        raise OSError("security unavailable")

    monkeypatch.setattr(credentials.subprocess, "run", fail_run)
    credentials.store_api_key("sk-fallback", settings)
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == "sk-fallback"
    assert credentials.load_api_key(settings) == "sk-fallback"


def test_darwin_migrates_legacy_plaintext_key(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    settings = _make_settings(tmp_path)
    settings.setValue(credentials.QSETTINGS_PLAIN_KEY, "sk-legacy-mac")
    settings.sync()

    keychain: dict[tuple[str, str], str] = {}

    def fake_run(cmd, **_kwargs):
        action = cmd[1]
        if action == "find-generic-password":
            svc = cmd[cmd.index("-s") + 1]
            acc = cmd[cmd.index("-a") + 1]
            if (svc, acc) in keychain:
                return subprocess.CompletedProcess(cmd, 0, stdout=keychain[(svc, acc)] + "\n", stderr="")
            return subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")
        if action == "add-generic-password":
            svc = cmd[cmd.index("-s") + 1]
            acc = cmd[cmd.index("-a") + 1]
            pw = cmd[cmd.index("-w") + 1]
            keychain[(svc, acc)] = pw
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(credentials.subprocess, "run", fake_run)

    loaded = credentials.load_api_key(settings)
    assert loaded == "sk-legacy-mac"
    assert keychain[(credentials.SERVICE_NAME, credentials.ACCOUNT_NAME)] == "sk-legacy-mac"
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""


def test_win32_dpapi_store_load_migrate_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    settings = _make_settings(tmp_path)
    allocated_buffers = []

    def fake_protect(p_in, _desc, _ent, _res, _prompt, _flags, p_out):
        in_blob = ctypes.cast(p_in, ctypes.POINTER(credentials._DataBlob)).contents
        out_blob = ctypes.cast(p_out, ctypes.POINTER(credentials._DataBlob)).contents
        raw = ctypes.string_at(in_blob.pbData, in_blob.cbData)
        enc = bytes(b ^ 0x5A for b in raw)
        buf = ctypes.create_string_buffer(enc, len(enc))
        allocated_buffers.append(buf)
        out_blob.cbData = len(enc)
        out_blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
        return 1

    def fake_unprotect(p_in, _desc, _ent, _res, _prompt, _flags, p_out):
        in_blob = ctypes.cast(p_in, ctypes.POINTER(credentials._DataBlob)).contents
        out_blob = ctypes.cast(p_out, ctypes.POINTER(credentials._DataBlob)).contents
        enc = ctypes.string_at(in_blob.pbData, in_blob.cbData)
        raw = bytes(b ^ 0x5A for b in enc)
        buf = ctypes.create_string_buffer(raw, len(raw))
        allocated_buffers.append(buf)
        out_blob.cbData = len(raw)
        out_blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
        return 1

    mock_windll = MagicMock()
    mock_windll.crypt32.CryptProtectData.side_effect = fake_protect
    mock_windll.crypt32.CryptUnprotectData.side_effect = fake_unprotect
    mock_windll.kernel32.LocalFree.return_value = 0
    monkeypatch.setattr(ctypes, "windll", mock_windll, raising=False)

    # Store using DPAPI
    settings.setValue(credentials.QSETTINGS_PLAIN_KEY, "stale-plain")
    credentials.store_api_key("sk-win-secret", settings)
    stored_b64 = settings.value(credentials.QSETTINGS_DPAPI_KEY, "")
    assert stored_b64
    assert base64.b64decode(stored_b64) != b"sk-win-secret"
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""
    assert credentials.load_api_key(settings) == "sk-win-secret"

    # Delete removes both keys
    credentials.delete_api_key(settings)
    assert settings.value(credentials.QSETTINGS_DPAPI_KEY, "") == ""
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""
    assert credentials.load_api_key(settings) == ""

    # Legacy plain-text migration
    settings.setValue(credentials.QSETTINGS_PLAIN_KEY, "sk-win-legacy")
    settings.sync()
    assert credentials.load_api_key(settings) == "sk-win-legacy"
    assert settings.value(credentials.QSETTINGS_DPAPI_KEY, "") != ""
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""

    # Fallback when CryptProtectData fails
    credentials.delete_api_key(settings)
    mock_windll.crypt32.CryptProtectData.side_effect = None
    mock_windll.crypt32.CryptProtectData.return_value = 0
    credentials.store_api_key("sk-win-fallback", settings)
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == "sk-win-fallback"
    assert credentials.load_api_key(settings) == "sk-win-fallback"


def test_linux_secret_tool_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    settings = _make_settings(tmp_path)
    secret_store: dict[str, str] = {}

    monkeypatch.setattr(credentials.shutil, "which", lambda name: "/usr/bin/secret-tool" if name == "secret-tool" else None)

    def fake_run(cmd, **kwargs):
        action = cmd[1]
        if action == "store":
            secret_store["key"] = kwargs["input"]
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if action == "lookup":
            if "key" in secret_store:
                return subprocess.CompletedProcess(cmd, 0, stdout=secret_store["key"], stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if action == "clear":
            secret_store.pop("key", None)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(credentials.subprocess, "run", fake_run)

    credentials.store_api_key("sk-linux-secret", settings)
    assert secret_store["key"] == "sk-linux-secret"
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""
    assert credentials.load_api_key(settings) == "sk-linux-secret"

    credentials.delete_api_key(settings)
    assert "key" not in secret_store
    assert credentials.load_api_key(settings) == ""

    # Legacy migration on Linux
    settings.setValue(credentials.QSETTINGS_PLAIN_KEY, "sk-linux-legacy")
    settings.sync()
    assert credentials.load_api_key(settings) == "sk-linux-legacy"
    assert secret_store["key"] == "sk-linux-legacy"
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""

    # Fallback when secret-tool is unavailable
    secret_store.clear()
    monkeypatch.setattr(credentials.shutil, "which", lambda _name: None)
    credentials.store_api_key("sk-linux-plain", settings)
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == "sk-linux-plain"
    assert credentials.load_api_key(settings) == "sk-linux-plain"


def test_store_empty_key_deletes_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(credentials.shutil, "which", lambda _name: None)
    settings = _make_settings(tmp_path)

    credentials.store_api_key("sk-temp", settings)
    assert credentials.load_api_key(settings) == "sk-temp"

    credentials.store_api_key("   ", settings)
    assert credentials.load_api_key(settings) == ""
    assert settings.value(credentials.QSETTINGS_PLAIN_KEY, "") == ""
