"""Real-time streaming transcript viewer with view switching (Polished vs Raw) and export actions."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
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
from whisper_gui.platform_utils import open_path_in_os, reveal_file_in_os
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_SURFACE,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_SECONDARY_HOVER,
    COLOR_SECONDARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
)


class TranscriptView(QGroupBox):
    """Displays real-time streaming transcription segments, progress bar, and export actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Live Transcript", parent)
        self._current_docx_path: Path | None = None
        self._raw_segments: list[TranscriptSegment] = []
        self._polished_text: str | None = None
        self._active_mode: str = "raw"  # "raw" or "polished"

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 8, 10, 8)

        # Progress bar & status header
        prog_header = QHBoxLayout()
        self.lbl_status = QLabel("Status: Idle")
        self.lbl_status.setStyleSheet(f"font-weight: bold; color: {COLOR_PRIMARY}; font-size: 11px;")
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")

        prog_header.addWidget(self.lbl_status)
        prog_header.addStretch()
        prog_header.addWidget(self.lbl_metrics)
        layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(14)
        layout.addWidget(self.progress_bar)

        # View mode selector bar (Polished vs Raw)
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(6)

        self.view_btn_group = QButtonGroup(self)
        self.btn_view_raw = QPushButton("Raw Segments")
        self.btn_view_raw.setCheckable(True)
        self.btn_view_raw.setChecked(True)
        self.btn_view_raw.setStyleSheet(f"""
            QPushButton {{
                padding: 3px 10px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {COLOR_BORDER};
            }}
            QPushButton:checked {{
                background-color: {COLOR_BG_INPUT};
                border: 1px solid {COLOR_PRIMARY};
                color: {COLOR_PRIMARY};
            }}
        """)
        self.view_btn_group.addButton(self.btn_view_raw)
        mode_bar.addWidget(self.btn_view_raw)

        self.btn_view_polished = QPushButton("Polished Text")
        self.btn_view_polished.setCheckable(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_view_polished.setStyleSheet(f"""
            QPushButton {{
                padding: 3px 10px;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid {COLOR_BORDER};
            }}
            QPushButton:checked {{
                background-color: #261622;
                border: 1px solid {COLOR_SECONDARY};
                color: {COLOR_SECONDARY};
            }}
            QPushButton:disabled {{
                color: {COLOR_TEXT_HINT};
            }}
        """)
        self.view_btn_group.addButton(self.btn_view_polished)
        mode_bar.addWidget(self.btn_view_polished)

        self.lbl_view_hint = QLabel("")
        self.lbl_view_hint.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 10px; font-style: italic;")
        mode_bar.addWidget(self.lbl_view_hint)

        mode_bar.addStretch()
        layout.addLayout(mode_bar)

        # Text stream display
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(True)
        self.txt_display.setPlaceholderText("Transcribed text and segments will stream here in real time...")
        self.txt_display.setMinimumHeight(120)
        self.txt_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_MAIN};
                font-family: -apple-system, "Segoe UI", Roboto, monospace, sans-serif;
                font-size: 12px;
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                padding: 8px;
                line-height: 1.4;
            }}
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Bottom action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_open_docx = QPushButton("Open Document")
        self.btn_open_docx.setToolTip("Open generated Word document in default office application")
        self.btn_open_docx.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SECONDARY};
                color: {COLOR_SECONDARY_TEXT};
                border: 1px solid {COLOR_SECONDARY};
                font-weight: bold;
                padding: 5px 14px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_SECONDARY_HOVER};
            }}
            QPushButton:disabled {{
                border: 1px solid {COLOR_BORDER};
                color: {COLOR_TEXT_HINT};
                background-color: {COLOR_BG_INPUT};
            }}
        """)
        self.btn_open_docx.setEnabled(False)
        btn_layout.addWidget(self.btn_open_docx)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.setToolTip("Open folder containing the Word document")
        self.btn_open_folder.setStyleSheet(f"""
            QPushButton:hover {{
                border: 1px solid {COLOR_SECONDARY};
                color: {COLOR_SECONDARY};
            }}
        """)
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_copy = QPushButton("Copy Text")
        self.btn_copy.setToolTip("Copy active transcript text to clipboard")
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                background-color: #17262D;
                color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
                font-weight: bold;
                padding: 5px 14px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
            }}
        """)
        btn_layout.addWidget(self.btn_copy)

        self.btn_clear = QPushButton("Clear")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Connect signals
        self.btn_view_raw.clicked.connect(lambda: self._switch_view("raw"))
        self.btn_view_polished.clicked.connect(lambda: self._switch_view("polished"))
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
        self._raw_segments.append(segment)
        if self._active_mode == "raw":
            cursor = self.txt_display.textCursor()
            cursor.movePosition(QTextCursor.End)

            ts_escaped = html.escape(segment.formatted_timerange)
            text_escaped = html.escape(segment.text)
            ts_html = f"<span style='color: {COLOR_PRIMARY}; font-weight: bold;'>{ts_escaped}</span>"
            text_html = f" <span style='color: {COLOR_TEXT_MAIN};'>{text_escaped}</span><br>"

            cursor.insertHtml(f"{ts_html}{text_html}")
            self.txt_display.setTextCursor(cursor)
            self.txt_display.ensureCursorVisible()

    def set_polished_text(self, text: str, model_name: str = "") -> None:
        """Store polished text and switch view to it."""
        self._polished_text = text
        self.btn_view_polished.setEnabled(bool(text.strip()))
        if text.strip():
            self.btn_view_polished.setChecked(True)
            self._switch_view("polished")
            info = f"Polished with {model_name}" if model_name else "Polished with LLM"
            self.lbl_view_hint.setText(f"({info})")

    def _switch_view(self, mode: str) -> None:
        self._active_mode = mode
        self.txt_display.clear()

        if mode == "polished" and self._polished_text:
            self.txt_display.setPlainText(self._polished_text)
        else:
            # Render raw segments
            cursor = self.txt_display.textCursor()
            for seg in self._raw_segments:
                ts_escaped = html.escape(seg.formatted_timerange)
                text_escaped = html.escape(seg.text)
                ts_html = f"<span style='color: {COLOR_PRIMARY}; font-weight: bold;'>{ts_escaped}</span>"
                text_html = f" <span style='color: {COLOR_TEXT_MAIN};'>{text_escaped}</span><br>"
                cursor.insertHtml(f"{ts_html}{text_html}")
            self.txt_display.setTextCursor(cursor)

    def set_completed_docx(self, docx_path: Path) -> None:
        """Mark document as ready and enable open actions."""
        self._current_docx_path = docx_path
        self.btn_open_docx.setEnabled(True)
        self.btn_open_folder.setEnabled(True)

    def clear_view(self) -> None:
        """Clear transcription output and reset progress."""
        self._raw_segments.clear()
        self._polished_text = None
        self._active_mode = "raw"
        self.txt_display.clear()
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Idle")
        self.lbl_metrics.setText("")
        self.lbl_view_hint.setText("")
        self.btn_view_raw.setChecked(True)
        self.btn_view_polished.setEnabled(False)
        self._current_docx_path = None
        self.btn_open_docx.setEnabled(False)
        self.btn_open_folder.setEnabled(False)

    def _open_docx_file(self) -> None:
        if self._current_docx_path and self._current_docx_path.exists():
            success = open_path_in_os(self._current_docx_path)
            if not success:
                self.lbl_status.setText(f"Could not open file: {self._current_docx_path.name}")

    def _open_containing_folder(self) -> None:
        if self._current_docx_path and self._current_docx_path.exists():
            success = reveal_file_in_os(self._current_docx_path)
            if not success:
                self.lbl_status.setText(f"Could not open directory: {self._current_docx_path.parent}")
        elif self._current_docx_path and self._current_docx_path.parent.exists():
            success = open_path_in_os(self._current_docx_path.parent)
            if not success:
                self.lbl_status.setText(f"Could not open directory: {self._current_docx_path.parent}")

    def _copy_text(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_display.toPlainText())
            self.lbl_status.setText("Status: Text copied to clipboard!")
