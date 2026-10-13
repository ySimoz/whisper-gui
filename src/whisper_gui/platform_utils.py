"""Cross-platform operating system abstractions for file handling, processes, and binaries."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


def is_bundled() -> bool:
    """Check if the application is running in a frozen/bundled state (e.g., PyInstaller)."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_bundle_dir() -> Path:
    """Return the base directory where application resources and binaries are located."""
    if is_bundled():
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent.parent.parent


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Sanitize a filename to ensure validity across Windows, macOS, and Linux.

    Windows prohibits: < > : " / \\ | ? *
    POSIX prohibits: / and NUL
    """
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', replacement, name)
    cleaned = cleaned.strip(". ")
    return cleaned if cleaned else "transcript"


def find_binary(binary_name: str) -> str | None:
    """Find a binary executable across system PATH, application directory, and bundled paths.

    Args:
        binary_name: Name of binary (e.g. 'ffmpeg', 'ffprobe').

    Returns:
        Absolute path string to executable if found, or None.
    """
    env_var_name = f"{binary_name.upper()}_PATH"
    if env_var_name in os.environ and os.path.isfile(os.environ[env_var_name]):
        return str(Path(os.environ[env_var_name]).resolve())

    candidates: list[Path] = []
    exe_suffixes = [".exe", ".cmd", ".bat"] if sys.platform.startswith("win") else ["", ".sh"]

    # 1. Bundled directory (PyInstaller _MEIPASS)
    if is_bundled():
        base = get_bundle_dir()
        for sfx in exe_suffixes:
            candidates.append(base / f"{binary_name}{sfx}")
            candidates.append(base / "bin" / f"{binary_name}{sfx}")

    # 2. Directory containing sys.executable (for standalone folder distributions)
    exe_dir = Path(sys.executable).parent
    for sfx in exe_suffixes:
        candidates.append(exe_dir / f"{binary_name}{sfx}")
        candidates.append(exe_dir / "bin" / f"{binary_name}{sfx}")

    # 3. Project / Application source root directory
    app_root = Path(__file__).resolve().parent.parent.parent
    for sfx in exe_suffixes:
        candidates.append(app_root / "bin" / f"{binary_name}{sfx}")
        candidates.append(app_root / f"{binary_name}{sfx}")

    # 4. Standard platform directories
    if sys.platform == "darwin":
        candidates.extend([
            Path(f"/opt/homebrew/bin/{binary_name}"),
            Path(f"/usr/local/bin/{binary_name}"),
            Path(f"/usr/bin/{binary_name}"),
        ])
    elif sys.platform.startswith("win"):
        candidates.extend([
            Path(f"C:\\ffmpeg\\bin\\{binary_name}.exe"),
            Path(f"C:\\Program Files\\ffmpeg\\bin\\{binary_name}.exe"),
            Path(f"C:\\ProgramData\\chocolatey\\bin\\{binary_name}.exe"),
        ])

    for cand in candidates:
        if cand.is_file() and (sys.platform.startswith("win") or os.access(cand, os.X_OK)):
            return str(cand.resolve())

    # 5. System PATH via shutil.which
    found = shutil.which(binary_name)
    if found:
        return str(Path(found).resolve())

    if sys.platform.startswith("win") and not binary_name.endswith(".exe"):
        found = shutil.which(f"{binary_name}.exe")
        if found:
            return str(Path(found).resolve())

    return None


def get_subprocess_creation_flags() -> dict:
    """Return platform-specific kwargs for spawning subprocesses cleanly in GUI apps.

    On Windows GUI apps (PyInstaller --noconsole), without CREATE_NO_WINDOW,
    spawning a subprocess either opens a black console window or crashes with Invalid Handle.
    """
    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        # On POSIX, start a new process session so the process tree can be killed cleanly
        kwargs["start_new_session"] = True
    return kwargs


def terminate_process_cross_platform(process: subprocess.Popen, grace: float = 2.0) -> None:
    """Safely terminate a subprocess tree across Windows, macOS, and Linux without crashing."""
    if process.poll() is not None:
        return

    # Windows handling
    if sys.platform.startswith("win"):
        try:
            process.terminate()
            try:
                process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                pass

            # Force kill the process and all child processes via taskkill
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        return

    # POSIX handling (Linux and macOS)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, AttributeError):
        try:
            process.terminate()
        except Exception:
            return

    deadline = time.time() + grace
    while time.time() < deadline:
        if process.poll() is not None:
            return
        time.sleep(0.05)

    try:
        sig_kill = getattr(signal, "SIGKILL", signal.SIGTERM)
        os.killpg(process.pid, sig_kill)
    except (ProcessLookupError, AttributeError):
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=1.0)
    except Exception:
        pass


def open_path_in_os(path: Path | str) -> bool:
    """Open a file or folder in the default system handler across Windows, macOS, and Linux.

    Uses Qt's QDesktopServices first, with native OS fallbacks (os.startfile, open, xdg-open).
    """
    p = Path(path).resolve()
    if not p.exists():
        return False

    # 1. Native Qt QDesktopServices (universal)
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        url = QUrl.fromLocalFile(str(p))
        if QDesktopServices.openUrl(url):
            return True
    except Exception:
        pass

    # 2. Platform-specific fallbacks
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
            return True
        else:
            subprocess.Popen(["xdg-open", str(p)])
            return True
    except Exception:
        return False
