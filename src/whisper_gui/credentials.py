"""OS-native secure storage for the LLM API key with QSettings fallback."""

from __future__ import annotations

import base64
import ctypes
import logging
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

SERVICE_NAME = "WhisperGUI"
ACCOUNT_NAME = "llm_api_key"
QSETTINGS_PLAIN_KEY = "LLM/api_key"
QSETTINGS_DPAPI_KEY = "LLM/api_key_dpapi"
_SUBPROCESS_TIMEOUT = 5


class _DataBlob(ctypes.Structure):
    """Windows DPAPI DATA_BLOB structure."""

    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _darwin_store(key: str) -> bool:
    try:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                SERVICE_NAME,
                "-a",
                ACCOUNT_NAME,
                "-w",
                key,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("macOS Keychain store failed, falling back to QSettings: %s", exc)
        return False


def _darwin_load() -> str | None:
    try:
        res = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                SERVICE_NAME,
                "-a",
                ACCOUNT_NAME,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if res.returncode == 0:
            return res.stdout.rstrip("\r\n")
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("macOS Keychain lookup failed: %s", exc)
        return None


def _darwin_delete() -> None:
    try:
        subprocess.run(
            [
                "security",
                "delete-generic-password",
                "-s",
                SERVICE_NAME,
                "-a",
                ACCOUNT_NAME,
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _dpapi_protect(plaintext: str) -> str | None:
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        crypt32 = windll.crypt32
        kernel32 = windll.kernel32
    except Exception:
        return None

    raw = plaintext.encode("utf-8")
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob_in = _DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DataBlob()

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        SERVICE_NAME,
        None,
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    ):
        return None

    try:
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(b64_ciphertext: str) -> str | None:
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        crypt32 = windll.crypt32
        kernel32 = windll.kernel32
        encrypted = base64.b64decode(b64_ciphertext)
    except Exception:
        return None

    buf = ctypes.create_string_buffer(encrypted, len(encrypted))
    blob_in = _DataBlob(len(encrypted), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DataBlob()

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    ):
        return None

    try:
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return decrypted.decode("utf-8")
    except Exception:
        return None
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(blob_out.pbData)


def _secret_tool_store(key: str) -> bool:
    if not shutil.which("secret-tool"):
        return False
    try:
        subprocess.run(
            [
                "secret-tool",
                "store",
                "--label=WhisperGUI LLM API Key",
                "service",
                SERVICE_NAME,
                "account",
                ACCOUNT_NAME,
            ],
            input=key,
            check=True,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("secret-tool store failed, falling back to QSettings: %s", exc)
        return False


def _secret_tool_load() -> str | None:
    if not shutil.which("secret-tool"):
        return None
    try:
        res = subprocess.run(
            [
                "secret-tool",
                "lookup",
                "service",
                SERVICE_NAME,
                "account",
                ACCOUNT_NAME,
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if res.returncode == 0 and res.stdout:
            return res.stdout.rstrip("\r\n")
        return None
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("secret-tool lookup failed: %s", exc)
        return None


def _secret_tool_delete() -> None:
    if not shutil.which("secret-tool"):
        return
    try:
        subprocess.run(
            [
                "secret-tool",
                "clear",
                "service",
                SERVICE_NAME,
                "account",
                ACCOUNT_NAME,
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _store_in_secure_backend(key: str, settings: QSettings) -> bool:
    """Try storing key in the active platform's secure backend. Returns True on success."""
    platform = sys.platform
    if platform == "darwin":
        return _darwin_store(key)
    if platform == "win32":
        encrypted_b64 = _dpapi_protect(key)
        if encrypted_b64:
            settings.setValue(QSETTINGS_DPAPI_KEY, encrypted_b64)
            return True
        return False
    return _secret_tool_store(key)


def store_api_key(key: str, settings: QSettings) -> None:
    """Persist the LLM API key in the OS credential store, falling back to QSettings."""
    clean_key = (key or "").strip()
    if not clean_key:
        delete_api_key(settings)
        return

    if _store_in_secure_backend(clean_key, settings):
        settings.remove(QSETTINGS_PLAIN_KEY)
    else:
        settings.setValue(QSETTINGS_PLAIN_KEY, clean_key)
    settings.sync()


def load_api_key(settings: QSettings) -> str:
    """Load the LLM API key from OS credential store, migrating any legacy plain-text key."""
    platform = sys.platform
    plain = str(settings.value(QSETTINGS_PLAIN_KEY, "", type=str) or "").strip()
    secret: str | None = None

    if platform == "darwin":
        secret = _darwin_load()
    elif platform == "win32":
        dpapi_b64 = str(settings.value(QSETTINGS_DPAPI_KEY, "", type=str) or "").strip()
        if dpapi_b64:
            secret = _dpapi_unprotect(dpapi_b64)
    else:
        secret = _secret_tool_load()

    if secret:
        if plain:
            settings.remove(QSETTINGS_PLAIN_KEY)
            settings.sync()
        return secret

    if plain:
        if _store_in_secure_backend(plain, settings):
            settings.remove(QSETTINGS_PLAIN_KEY)
            settings.sync()
        return plain

    return ""


def delete_api_key(settings: QSettings) -> None:
    """Remove the stored LLM API key from OS credential store and QSettings."""
    platform = sys.platform
    if platform == "darwin":
        _darwin_delete()
    elif platform != "win32":
        _secret_tool_delete()

    settings.remove(QSETTINGS_PLAIN_KEY)
    settings.remove(QSETTINGS_DPAPI_KEY)
    settings.sync()
