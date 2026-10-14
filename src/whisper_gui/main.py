"""CLI / GUI entrypoint for Whisper GUI application with bundling freeze support."""

from __future__ import annotations

import multiprocessing
import os
import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from whisper_gui import __version__
from whisper_gui.platform_utils import get_app_icon
from whisper_gui.ui.main_window import MainWindow


def main() -> int:
    """Launch Whisper GUI desktop application."""
    # Essential for PyInstaller / cx_Freeze / multiprocessing on Windows
    multiprocessing.freeze_support()

    # Enable smooth high-DPI scaling across Windows, macOS, and Linux
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Whisper GUI")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("WhisperGUI")
    app.setDesktopFileName("whisper-gui.desktop")

    # Set application icon
    app_icon = get_app_icon()
    if app_icon and not app_icon.isNull():
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if app_icon and not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
