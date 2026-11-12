"""Auto-update checking, downloading, extraction, and self-replacement via GitHub Releases."""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from whisper_gui import __version__
from whisper_gui.llm_cleaner import get_ssl_context
from whisper_gui.platform_utils import get_subprocess_creation_flags, is_bundled

logger = logging.getLogger(__name__)

GITHUB_REPO = "ySimoz/whisper-gui"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass(frozen=True)
class ReleaseInfo:
    """Metadata for an available GitHub release."""

    version: str
    tag_name: str
    changelog: str
    html_url: str
    asset_name: str | None = None
    download_url: str | None = None
    asset_size: int = 0


def parse_version(version_str: str) -> tuple[tuple[int, ...], str] | None:
    """Parse a semantic version string (e.g. 'v0.2.1', '0.1.0-rc1').

    Returns None for non-numeric tags such as 'latest-build'.
    """
    cleaned = (version_str or "").strip().lstrip("vV")
    if not cleaned:
        return None
    cleaned = cleaned.split("+", 1)[0]
    match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:-([0-9A-Za-z.-]+))?", cleaned)
    if not match:
        return None
    nums = tuple(int(part) for part in match.group(1).split("."))
    prerelease = match.group(2) or ""
    return nums, prerelease


def is_newer_version(latest_tag: str, current_version: str = __version__) -> bool:
    """Return True when latest_tag represents a strictly newer version than current_version."""
    latest = parse_version(latest_tag)
    current = parse_version(current_version)
    if latest is None or current is None:
        return False

    l_nums, l_pre = latest
    c_nums, c_pre = current
    max_len = max(len(l_nums), len(c_nums))
    l_padded = l_nums + (0,) * (max_len - len(l_nums))
    c_padded = c_nums + (0,) * (max_len - len(c_nums))

    if l_padded != c_padded:
        return l_padded > c_padded
    # Same numeric version: stable release > prerelease
    if bool(l_pre) != bool(c_pre):
        return not l_pre
    return l_pre > c_pre


def select_asset_for_platform(
    assets: list[dict],
    platform_name: str | None = None,
) -> dict | None:
    """Pick the matching release archive asset for the current operating system."""
    plat = platform_name or sys.platform
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if plat == "darwin" and "macos" in name and name.endswith(".zip"):
            return asset
        if plat.startswith("win") and "windows" in name and name.endswith(".zip"):
            return asset
        if plat.startswith("linux") and "linux" in name and (
            name.endswith(".tar.gz") or name.endswith(".tgz")
        ):
            return asset
    return None


def fetch_latest_release(
    current_version: str = __version__,
    timeout: float = 8.0,
    api_url: str = LATEST_RELEASE_API,
    platform_name: str | None = None,
) -> ReleaseInfo | None:
    """Check GitHub Releases for a newer version. Returns None if up to date or offline."""
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"WhisperGUI/{current_version}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("Update check skipped or failed: %s", exc)
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("draft") or payload.get("prerelease"):
        return None

    tag_name = str(payload.get("tag_name") or "").strip()
    if not is_newer_version(tag_name, current_version):
        return None

    asset = select_asset_for_platform(payload.get("assets") or [], platform_name=platform_name)
    download_url = str(asset.get("browser_download_url") or "") if asset else None
    if download_url and not download_url.startswith("https://"):
        download_url = None

    return ReleaseInfo(
        version=tag_name.lstrip("vV"),
        tag_name=tag_name,
        changelog=str(payload.get("body") or "").strip(),
        html_url=str(payload.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"),
        asset_name=str(asset.get("name")) if asset else None,
        download_url=download_url,
        asset_size=int(asset.get("size") or 0) if asset else 0,
    )


def download_release_asset(
    url: str,
    dest_path: Path,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float = 30.0,
) -> Path:
    """Download a release archive to dest_path over HTTPS with progress and cancellation."""
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS update URL: {url}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest_path.with_name(dest_path.name + ".part")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"WhisperGUI/{__version__}"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(part_path, "wb") as out:
                while True:
                    if cancel_check and cancel_check():
                        raise InterruptedError("Update download cancelled")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total)
        part_path.replace(dest_path)
        return dest_path
    except Exception:
        part_path.unlink(missing_ok=True)
        raise


def get_install_target(
    executable_path: str | Path | None = None,
    platform_name: str | None = None,
) -> Path | None:
    """Return the app bundle (.app) or installation directory to replace when bundled."""
    if executable_path is None and not is_bundled():
        return None

    exe = Path(executable_path or sys.executable).resolve()
    plat = platform_name or sys.platform
    if plat == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
    return exe.parent


def is_writable_target(target: Path) -> bool:
    """Check whether the user can replace target without admin elevation."""
    parent = target.parent
    if not os.access(parent, os.W_OK):
        return False
    if target.exists() and not os.access(target, os.W_OK):
        return False
    return True


def _validate_archive_member(extract_root: Path, member_name: str) -> None:
    """Prevent path traversal outside extract_root."""
    target = (extract_root / member_name).resolve()
    root_resolved = extract_root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError(f"Unsafe archive entry path: {member_name}")


def _find_extracted_app(extract_dir: Path, plat: str) -> Path:
    """Locate the top-level .app bundle or WhisperGUI folder inside extract_dir."""
    if plat == "darwin":
        for candidate in extract_dir.rglob("*.app"):
            if candidate.is_dir() and len(candidate.relative_to(extract_dir).parts) <= 2:
                return candidate
        raise FileNotFoundError("WhisperGUI.app not found in downloaded archive")

    exe_name = "WhisperGUI.exe" if plat.startswith("win") else "WhisperGUI"
    direct_folder = extract_dir / "WhisperGUI"
    if (direct_folder / exe_name).is_file():
        return direct_folder
    if (extract_dir / exe_name).is_file():
        return extract_dir
    for match in extract_dir.rglob(exe_name):
        if match.is_file():
            return match.parent
    raise FileNotFoundError(f"{exe_name} not found in downloaded archive")


def extract_release_archive(
    archive_path: Path,
    extract_dir: Path,
    platform_name: str | None = None,
) -> Path:
    """Extract a release zip or tar.gz archive safely and return the extracted app path."""
    plat = platform_name or sys.platform
    extract_dir.mkdir(parents=True, exist_ok=True)
    name_lower = archive_path.name.lower()

    if name_lower.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                _validate_archive_member(extract_dir, member.name)
            if hasattr(tarfile, "data_filter"):
                tf.extractall(extract_dir, filter="data")
            else:
                tf.extractall(extract_dir)
    elif name_lower.endswith(".zip"):
        if plat == "darwin" and shutil.which("ditto"):
            # ditto preserves macOS symlinks, framework bundles, and executable permissions
            subprocess.run(
                ["ditto", "-xk", str(archive_path), str(extract_dir)],
                check=True,
                capture_output=True,
            )
        else:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    _validate_archive_member(extract_dir, info.filename)
                zf.extractall(extract_dir)
                if not plat.startswith("win"):
                    for info in zf.infolist():
                        mode = (info.external_attr >> 16) & 0o777
                        if mode and not info.is_dir():
                            extracted = extract_dir / info.filename
                            if extracted.is_file():
                                os.chmod(extracted, mode)
    else:
        raise ValueError(f"Unsupported archive format: {archive_path.name}")

    return _find_extracted_app(extract_dir, plat)


def apply_update_and_relaunch(
    new_app_path: Path,
    target_app_path: Path,
    current_pid: int | None = None,
    platform_name: str | None = None,
) -> None:
    """Spawn a detached helper script to swap target_app_path after exit and relaunch."""
    if not is_writable_target(target_app_path):
        raise PermissionError(
            f"No write permission to replace {target_app_path}. "
            "Move the app to a user-writable folder or install manually."
        )

    pid = current_pid if current_pid is not None else os.getpid()
    plat = platform_name or sys.platform
    backup_path = target_app_path.with_name(target_app_path.name + ".bak")
    flags = get_subprocess_creation_flags()

    if plat.startswith("win"):
        script_path = Path(tempfile.gettempdir()) / f"whisper_gui_update_{pid}.bat"
        tgt = str(target_app_path)
        bak = str(backup_path)
        new = str(new_app_path)
        exe = str(target_app_path / "WhisperGUI.exe")
        script = "\r\n".join([
            "@echo off",
            "setlocal",
            "for /L %%i in (1,1,30) do (",
            f'  tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul',
            "  if errorlevel 1 goto swap",
            "  ping -n 2 127.0.0.1 >nul",
            ")",
            ":swap",
            f'if exist "{bak}" rmdir /S /Q "{bak}"',
            f'if exist "{tgt}" move "{tgt}" "{bak}" >nul',
            f'move "{new}" "{tgt}" >nul',
            "if errorlevel 1 (",
            f'  xcopy /E /I /H /Y /Q "{new}" "{tgt}\\" >nul',
            f'  if not errorlevel 1 rmdir /S /Q "{new}"',
            ")",
            f'if exist "{tgt}\\WhisperGUI.exe" (',
            f'  if exist "{bak}" rmdir /S /Q "{bak}"',
            f'  start "" "{exe}"',
            ") else (",
            f'  if exist "{bak}" move "{bak}" "{tgt}" >nul',
            ")",
            '(goto) 2>nul & del "%~f0"',
        ])
        script_path.write_text(script, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(script_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **flags,
        )
        return

    script_path = Path(tempfile.gettempdir()) / f"whisper_gui_update_{pid}.sh"
    q_tgt = shlex.quote(str(target_app_path))
    q_bak = shlex.quote(str(backup_path))
    q_new = shlex.quote(str(new_app_path))
    relaunch_cmd = (
        f"open -n {q_tgt}"
        if plat == "darwin"
        else f"nohup {shlex.quote(str(target_app_path / 'WhisperGUI'))} >/dev/null 2>&1 &"
    )
    extra_darwin = f"xattr -cr {q_tgt} >/dev/null 2>&1 || true\n" if plat == "darwin" else ""

    script = (
        "#!/bin/sh\n"
        "i=0\n"
        f"while kill -0 {pid} 2>/dev/null && [ $i -lt 30 ]; do\n"
        "  sleep 0.5\n"
        "  i=$((i + 1))\n"
        "done\n"
        f"rm -rf {q_bak}\n"
        f"if [ -e {q_tgt} ]; then mv {q_tgt} {q_bak}; fi\n"
        f"if mv {q_new} {q_tgt}; then\n"
        f"  rm -rf {q_bak}\n"
        f"  {extra_darwin}"
        f"  {relaunch_cmd}\n"
        "else\n"
        f"  if [ -e {q_bak} ] && [ ! -e {q_tgt} ]; then mv {q_bak} {q_tgt}; fi\n"
        "fi\n"
        'rm -f "$0"\n'
    )
    script_path.write_text(script, encoding="utf-8")
    os.chmod(script_path, 0o700)
    subprocess.Popen(
        ["/bin/sh", str(script_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **flags,
    )
