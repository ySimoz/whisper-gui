"""Real-time streaming transcript viewer with view switching (Polished vs Raw) and export actions."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.exporters import export_transcript
from whisper_gui.models import (
    AudioTrack,
    TranscriptionConfig,
    TranscriptionResult,
    TranscriptSegment,
)
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


class TranscriptView(QFrame):
    """Displays real-time streaming transcription segments, progress bar, and export actions."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_docx_path: Path | None = None
        self._current_track: AudioTrack | None = None
        self._current_result: TranscriptionResult | None = None
        self._current_config: TranscriptionConfig | None = None
        self._exported_paths: dict[str, Path] = {}
        self._raw_segments: list[TranscriptSegment] = []
        self._polished_text: str | None = None
        self._active_mode: str = "raw"  # "raw" or "polished"

        self.setObjectName("transcript_view")
        self.setStyleSheet(f"""
            #transcript_view {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 12, 14, 12)

        # Header: Title + Status + Metrics
        prog_header = QHBoxLayout()
        prog_header.setSpacing(8)

        lbl_section = QLabel("Transcript")
        lbl_section.setStyleSheet(f"font-weight: 700; color: {COLOR_TEXT_MAIN}; font-size: 13px;")
        prog_header.addWidget(lbl_section)

        self.lbl_status = QLabel("Idle")
        self.lbl_status.setStyleSheet(f"font-weight: 600; color: {COLOR_PRIMARY}; font-size: 12px;")
        prog_header.addWidget(self.lbl_status)

        prog_header.addStretch()
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        prog_header.addWidget(self.lbl_metrics)
        layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(8)
        layout.addWidget(self.progress_bar)

        # View mode selector bar (Raw vs Polished segmented control)
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(4)

        self.view_btn_group = QButtonGroup(self)
        self.btn_view_raw = QPushButton("Raw")
        self.btn_view_raw.setCheckable(True)
        self.btn_view_raw.setChecked(True)
        self.btn_view_raw.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
            QPushButton:checked {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
            }}
        """)
        self.view_btn_group.addButton(self.btn_view_raw)
        mode_bar.addWidget(self.btn_view_raw)

        self.btn_view_polished = QPushButton("Polished")
        self.btn_view_polished.setCheckable(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_view_polished.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
            QPushButton:checked {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
            }}
            QPushButton:disabled {{
                color: {COLOR_TEXT_HINT};
            }}
        """)
        self.view_btn_group.addButton(self.btn_view_polished)
        mode_bar.addWidget(self.btn_view_polished)

        self.lbl_view_hint = QLabel("")
        self.lbl_view_hint.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 10px;")
        mode_bar.addWidget(self.lbl_view_hint)

        mode_bar.addStretch()
        layout.addLayout(mode_bar)

        # Text stream display
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(True)
        self.txt_display.setPlaceholderText("Transcribed text appears here...")
        self.txt_display.setMinimumHeight(140)
        self.txt_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_MAIN};
                font-size: 13px;
                line-height: 1.6;
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Bottom action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_copy = QPushButton("Copy Text")
        self.btn_copy.setStyleSheet(f"""
            QPushButton {{
                font-weight: 600;
                padding: 6px 14px;
            }}
        """)
        btn_layout.addWidget(self.btn_copy)

        self.btn_export = QPushButton("Export ▾")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_BG_SURFACE};
                font-weight: 600;
                padding: 6px 14px;
            }}
            QPushButton::menu-indicator {{
                image: none;
                width: 0px;
            }}
            QPushButton:enabled {{
                border-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY};
            }}
        """)
        self.btn_export.setEnabled(False)
        self.btn_open_docx = self.btn_export  # Compatibility alias

        self.export_menu = QMenu(self)
        self.export_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
                color: {COLOR_TEXT_MAIN};
            }}
            QMenu::item:selected {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
            }}
        """)

        act_docx = self.export_menu.addAction("Word (.docx)")
        act_docx.triggered.connect(lambda: self._on_export_format("docx"))

        act_pdf = self.export_menu.addAction("PDF (.pdf)")
        act_pdf.triggered.connect(lambda: self._on_export_format("pdf"))

        act_md = self.export_menu.addAction("Markdown (.md)")
        act_md.triggered.connect(lambda: self._on_export_format("md"))

        act_txt = self.export_menu.addAction("Plain Text (.txt)")
        act_txt.triggered.connect(lambda: self._on_export_format("txt"))

        self.export_menu.addSeparator()

        act_folder = self.export_menu.addAction("Open Output Folder")
        act_folder.triggered.connect(self._open_containing_folder)

        self.btn_export.setMenu(self.export_menu)
        btn_layout.addWidget(self.btn_export)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.setStyleSheet("padding: 6px 12px;")
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet("padding: 6px 12px;")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Connect signals
        self.btn_view_raw.clicked.connect(lambda: self._switch_view("raw"))
        self.btn_view_polished.clicked.connect(lambda: self._switch_view("polished"))
        self.btn_open_folder.clicked.connect(self._open_containing_folder)
        self.btn_copy.clicked.connect(self._copy_text)
        self.btn_clear.clicked.connect(self._on_clear_clicked)

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

    def set_completed_track(
        self,
        track: AudioTrack,
        result: TranscriptionResult,
        config: TranscriptionConfig | None = None,
    ) -> None:
        """Store active completed track and result for on-demand multi-format export."""
        self._current_track = track
        self._current_result = result
        self._current_config = config

        if result.docx_path:
            self._current_docx_path = result.docx_path
            self._exported_paths["docx"] = result.docx_path
        if result.pdf_path:
            self._exported_paths["pdf"] = result.pdf_path
        if result.md_path:
            self._exported_paths["md"] = result.md_path
        if result.txt_path:
            self._exported_paths["txt"] = result.txt_path

        self.btn_export.setEnabled(True)
        self.btn_open_folder.setEnabled(True)

    def set_completed_docx(self, docx_path: Path) -> None:
        """Mark document as ready and enable export/folder actions."""
        self._current_docx_path = docx_path
        self._exported_paths["docx"] = docx_path
        self.btn_export.setEnabled(True)
        self.btn_open_folder.setEnabled(True)

    def _on_clear_clicked(self) -> None:
        """Prompt confirmation if content exists before clearing transcript view."""
        has_content = bool(
            self.txt_display.toPlainText().strip()
            or self._raw_segments
            or self._current_track
        )
        if has_content:
            reply = QMessageBox.question(
                self,
                "Clear Transcript",
                "Are you sure you want to clear the transcript? Any unsaved text will be removed.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.clear_view()

    def clear_view(self) -> None:
        """Clear transcription output and reset progress."""
        self._raw_segments.clear()
        self._polished_text = None
        self._active_mode = "raw"
        self._current_track = None
        self._current_result = None
        self._current_config = None
        self._exported_paths.clear()
        self._current_docx_path = None

        self.txt_display.clear()
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Status: Idle")
        self.lbl_metrics.setText("")
        self.lbl_view_hint.setText("")
        self.btn_view_raw.setChecked(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_open_folder.setEnabled(False)

    def _on_export_format(self, fmt: str) -> None:
        """Export or open the requested format: 'docx', 'pdf', 'md', 'txt'."""
        try:
            # 1. Open if already exported and exists
            existing_path = self._exported_paths.get(fmt)
            if existing_path and existing_path.exists():
                success = open_path_in_os(existing_path)
                if success:
                    self.lbl_status.setText(f"Status: Opened {existing_path.name}")
                else:
                    self.lbl_status.setText(f"Status: Saved {existing_path.name}")
                return

            # 2. Determine target path
            if self._current_track:
                target_dir = self._current_config.output_dir if self._current_config else None
                out_path = self._current_track.effective_export_path(fmt, target_dir)
            elif self._current_docx_path:
                out_path = self._current_docx_path.with_suffix(f".{fmt}")
            else:
                out_path = Path.home() / f"transcript.{fmt}"

            # 3. Perform export
            result_obj = self._current_result or TranscriptionResult(
                full_text=self.txt_display.toPlainText(),
                segments=self._raw_segments,
                polished_text=self._polished_text,
            )
            saved_path = export_transcript(
                format_name=fmt,
                output_path=out_path,
                track_info=self._current_track.info if self._current_track else None,
                slice_config=self._current_track.slice_config if self._current_track else None,
                transcription_config=self._current_config,
                result=result_obj,
            )
            self._exported_paths[fmt] = saved_path
            if fmt == "docx":
                self._current_docx_path = saved_path

            # 4. Open with default OS viewer
            success = open_path_in_os(saved_path)
            if success:
                self.lbl_status.setText(f"Status: Exported & opened {saved_path.name}")
            else:
                self.lbl_status.setText(f"Status: Exported to {saved_path.name}")
        except Exception as e:
            self.lbl_status.setText(f"Export Error: {e}")

    def _open_docx_file(self) -> None:
        self._on_export_format("docx")

    def _open_containing_folder(self) -> None:
        target = self._current_docx_path
        if not target and self._exported_paths:
            target = next(iter(self._exported_paths.values()))
        if not target and self._current_track:
            target = self._current_track.file_path
        if not target and self._current_config and self._current_config.output_dir:
            target = self._current_config.output_dir

        if target:
            p = Path(target).resolve()
            if p.is_file():
                success = reveal_file_in_os(p)
                if not success and p.parent.exists():
                    open_path_in_os(p.parent)
            elif p.is_dir() and p.exists():
                open_path_in_os(p)
            elif p.parent.exists():
                open_path_in_os(p.parent)
            else:
                self.lbl_status.setText(f"Status: Directory not found: {p}")
        else:
            self.lbl_status.setText("Status: No output folder available")

    def _copy_text(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_display.toPlainText())
            self.lbl_status.setText("Status: Text copied to clipboard!")
