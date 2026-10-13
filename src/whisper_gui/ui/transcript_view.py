"""Real-time streaming transcript viewer with cross-platform actions for .docx opening and copying."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.models import TranscriptSegment
from whisper_gui.platform_utils import open_path_in_os


class TranscriptView(QGroupBox):
    """Displays real-time streaming transcription segments, progress bar, and export actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Live Transcription & Export", parent)
        self._current_docx_path: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 8, 10, 8)

        # Progress bar & status header
        prog_header = QHBoxLayout()
        self.lbl_status = QLabel("Status: Idle")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #2c3e50; font-size: 12px;")
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet("color: #7f8c8d; font-size: 11px;")

        prog_header.addWidget(self.lbl_status)
        prog_header.addStretch()
        prog_header.addWidget(self.lbl_metrics)
        layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ced4da;
                border-radius: 3px;
                text-align: center;
                background-color: #f8f9fa;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Text stream display
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(True)
        self.txt_display.setPlaceholderText("Transcribed text and segments will stream here in real time...")
        self.txt_display.setMinimumHeight(120)
        self.txt_display.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                color: #212529;
                font-family: monospace, sans-serif;
                font-size: 12px;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Bottom action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_open_docx = QPushButton("📄 Open .docx")
        self.btn_open_docx.setToolTip("Open generated Word document in default office application")
        self.btn_open_docx.setStyleSheet("""
            QPushButton {
                background-color: #1a5276;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #7f8c8d;
            }
        """)
        self.btn_open_docx.setEnabled(False)
        btn_layout.addWidget(self.btn_open_docx)

        self.btn_open_folder = QPushButton("📁 Open Folder")
        self.btn_open_folder.setToolTip("Open folder containing the Word document")
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_copy = QPushButton("📋 Copy Text")
        self.btn_copy.setToolTip("Copy entire transcript to clipboard")
        btn_layout.addWidget(self.btn_copy)

        self.btn_clear = QPushButton("Clear")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Connect signals
        self.btn_open_docx.clicked.connect(self._open_docx_file)
        self.btn_open_folder.clicked.connect(self._open_containing_folder)
        self.btn_copy.clicked.connect(self._copy_text)
        self.btn_clear.clicked.connect(self.clear_view)

    def set_status(self, message: str) -> None:
        """Update the status label."""
        self.lbl_status.setText(f"Status: {message}")

    def set_progress(self, percent: int, metrics_text: str = "") -> None:
        """Update the progress bar and metrics."""
        self.progress_bar.setValue(max(0, min(100, percent)))
        if metrics_text:
            self.lbl_metrics.setText(metrics_text)

    def append_segment(self, segment: TranscriptSegment) -> None:
        """Append a newly streamed transcription segment."""
        cursor = self.txt_display.textCursor()
        cursor.movePosition(QTextCursor.End)

        ts_html = f"<span style='color: #2980b9; font-weight: bold;'>{segment.formatted_timerange}</span>"
        text_html = f" <span style='color: #2c3e50;'>{segment.text}</span><br>"

        cursor.insertHtml(f"{ts_html}{text_html}")
        self.txt_display.setTextCursor(cursor)
        self.txt_display.ensureCursorVisible()

    def set_completed_docx(self, docx_path: Path) -> None:
        """Mark document as ready and enable open actions."""
        self._current_docx_path = docx_path
        self.btn_open_docx.setEnabled(True)
        self.btn_open_folder.setEnabled(True)

    def clear_view(self) -> None:
        """Clear transcription output and reset progress."""
        self.txt_display.clear()
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Idle")
        self.lbl_metrics.setText("")
        self._current_docx_path = None
        self.btn_open_docx.setEnabled(False)
        self.btn_open_folder.setEnabled(False)

    def _open_docx_file(self) -> None:
        if self._current_docx_path and self._current_docx_path.exists():
            success = open_path_in_os(self._current_docx_path)
            if not success:
                self.lbl_status.setText(f"Could not open file: {self._current_docx_path.name}")

    def _open_containing_folder(self) -> None:
        if self._current_docx_path and self._current_docx_path.parent.exists():
            success = open_path_in_os(self._current_docx_path.parent)
            if not success:
                self.lbl_status.setText(f"Could not open directory: {self._current_docx_path.parent}")

    def _copy_text(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_display.toPlainText())
            self.lbl_status.setText("Status: Text copied to clipboard!")
