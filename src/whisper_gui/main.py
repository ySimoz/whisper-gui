"""CLI / GUI entrypoint for Whisper GUI application."""

import sys
from PySide6.QtWidgets import QApplication

from whisper_gui.ui.main_window import MainWindow


def main() -> int:
    """Launch Whisper GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Whisper GUI")
    app.setOrganizationName("WhisperGUI")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
