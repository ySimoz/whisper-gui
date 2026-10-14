#!/usr/bin/env python3
"""Build and bundle Whisper GUI into a standalone desktop application using PyInstaller."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    os.chdir(project_root)

    print(f"Building Whisper GUI on {platform.system()} ({platform.machine()})...")

    # Verify PyInstaller is installed
    try:
        import PyInstaller
        print(f"PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("Error: PyInstaller is not installed. Run: pip install pyinstaller")
        return 1

    spec_file = project_root / "whisper_gui.spec"
    if not spec_file.exists():
        print(f"Error: Spec file not found at {spec_file}")
        return 1

    # Clean previous build artifacts
    build_dir = project_root / "build"
    dist_dir = project_root / "dist"
    if build_dir.exists():
        print("Cleaning previous build directory...")
        shutil.rmtree(build_dir, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_file),
    ]

    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"Build failed with exit code {result.returncode}")
        return result.returncode

    print("\n" + "=" * 60)
    print("SUCCESS: Standalone application created successfully!")
    if sys.platform == "darwin":
        mac_app = dist_dir / "WhisperGUI.app"
        print(f"macOS Application: {mac_app}")
        print("You can double-click it or drag it to /Applications!")
    elif sys.platform.startswith("win"):
        output_app = dist_dir / "WhisperGUI"
        print(f"Windows Executable: {output_app / 'WhisperGUI.exe'}")
    else:
        output_app = dist_dir / "WhisperGUI"
        print(f"Linux Executable: {output_app / 'WhisperGUI'}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
