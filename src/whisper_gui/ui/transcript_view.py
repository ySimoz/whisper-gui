"""Real-time streaming transcript viewer with view switching (Polished vs Raw) and export actions."""

from __future__ import annotations

from dataclasses import replace
import html
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    CHEVRON_ICON_URL,
    COLOR_BG_INPUT,
    COLOR_BG_RAISED,
    COLOR_BG_SURFACE,
    COLOR_BORDER,
    COLOR_BORDER_LIGHT,
    COLOR_PRIMARY,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
    fixed_mono_font,
    load_ui_icon,
)


class TranscriptView(QFrame):
    """Displays real-time streaming transcription segments, progress bar, and export actions."""

    polish_requested = Signal()

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
        self._updating_text: bool = False
        self._raw_edited: bool = False
        self._raw_edited_text: str | None = None
        self._raw_segments_stale: bool = False

        self.setObjectName("transcript_view")
        self.setStyleSheet(f"""
            #transcript_view {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 12, 16, 12)

        # Header: Title + Status + Metrics
        prog_header = QHBoxLayout()
        prog_header.setSpacing(8)

        lbl_section = QLabel("Transcript")
        lbl_section.setStyleSheet(f"font-weight: 500; color: {COLOR_TEXT_MAIN}; font-size: 13px;")
        prog_header.addWidget(lbl_section)

        self.lbl_status = QLabel("Idle")
        self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px;")
        prog_header.addWidget(self.lbl_status)

        prog_header.addStretch()
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setFont(fixed_mono_font(11))
        self.lbl_metrics.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        prog_header.addWidget(self.lbl_metrics)
        layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)

        # View mode selector bar (Raw vs Polished segmented control)
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(4)

        seg_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {COLOR_TEXT_MUTED};
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QPushButton:hover:enabled {{
                color: {COLOR_TEXT_MAIN};
                background-color: {COLOR_BG_RAISED};
            }}
            QPushButton:checked {{
                background-color: {COLOR_BG_RAISED};
                border: 1px solid {COLOR_BORDER_LIGHT};
                color: {COLOR_TEXT_MAIN};
            }}
            QPushButton:disabled {{
                color: {COLOR_TEXT_HINT};
                background-color: transparent;
            }}
        """

        self.view_btn_group = QButtonGroup(self)
        self.btn_view_raw = QPushButton("Raw")
        self.btn_view_raw.setCheckable(True)
        self.btn_view_raw.setChecked(True)
        self.btn_view_raw.setStyleSheet(seg_btn_style)
        self.view_btn_group.addButton(self.btn_view_raw)
        mode_bar.addWidget(self.btn_view_raw)

        self.btn_view_polished = QPushButton("Polished")
        self.btn_view_polished.setCheckable(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_view_polished.setStyleSheet(seg_btn_style)
        self.view_btn_group.addButton(self.btn_view_polished)
        mode_bar.addWidget(self.btn_view_polished)

        self.btn_polish = QPushButton("Polish")
        self.btn_polish.setEnabled(False)
        self.btn_polish.setToolTip("Polish or re-polish transcript with LLM without re-transcribing")
        self.btn_polish.setStyleSheet(seg_btn_style)
        mode_bar.addWidget(self.btn_polish)

        self.lbl_view_hint = QLabel("")
        self.lbl_view_hint.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px; padding-left: 4px;")
        mode_bar.addWidget(self.lbl_view_hint)

        mode_bar.addStretch()

        self.btn_find = QPushButton("Find")
        self.btn_find.setCheckable(True)
        self.btn_find.setToolTip("Find in transcript (Ctrl/Cmd+F)")
        self.btn_find.setStyleSheet(seg_btn_style)
        mode_bar.addWidget(self.btn_find)
        layout.addLayout(mode_bar)

        # Collapsible Find bar (hidden by default)
        self.find_bar = QFrame()
        self.find_bar.setVisible(False)
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(0, 0, 0, 0)
        find_layout.setSpacing(4)

        self.txt_find = QLineEdit()
        self.txt_find.setPlaceholderText("Find in transcript")
        self.txt_find.setClearButtonEnabled(True)
        find_layout.addWidget(self.txt_find, stretch=1)

        self.btn_find_prev = QPushButton("Prev")
        self.btn_find_prev.setToolTip("Previous match")
        self.btn_find_prev.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        find_layout.addWidget(self.btn_find_prev)

        self.btn_find_next = QPushButton("Next")
        self.btn_find_next.setToolTip("Next match")
        self.btn_find_next.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        find_layout.addWidget(self.btn_find_next)

        self.lbl_find_status = QLabel("")
        self.lbl_find_status.setFont(fixed_mono_font(11))
        self.lbl_find_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; padding: 0 4px;")
        find_layout.addWidget(self.lbl_find_status)

        self.btn_find_close = QPushButton()
        self.btn_find_close.setIcon(load_ui_icon("close"))
        self.btn_find_close.setFixedSize(28, 28)
        self.btn_find_close.setToolTip("Close find bar")
        self.btn_find_close.setStyleSheet("padding: 0px;")
        find_layout.addWidget(self.btn_find_close)

        layout.addWidget(self.find_bar)

        # Text stream display
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(False)
        self.txt_display.setPlaceholderText("Transcribed text appears here")
        self.txt_display.setMinimumHeight(140)
        self.txt_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_MAIN};
                font-size: 13px;
                line-height: 1.6;
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        layout.addWidget(self.txt_display, stretch=1)

        # Bottom action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_copy = QPushButton("Copy Text")
        self.btn_copy.setStyleSheet("padding: 6px 12px;")
        btn_layout.addWidget(self.btn_copy)

        self.btn_export = QPushButton("Export")
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                padding: 6px 24px 6px 12px;
            }}
            QPushButton::menu-indicator {{
                image: url({CHEVRON_ICON_URL});
                subcontrol-origin: padding;
                subcontrol-position: right center;
                right: 8px;
                width: 12px;
                height: 12px;
            }}
        """)
        self.btn_export.setEnabled(False)
        self.btn_open_docx = self.btn_export  # Compatibility alias

        self.export_menu = QMenu(self)
        self.export_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 6px 20px 6px 12px;
                border-radius: 4px;
                color: {COLOR_TEXT_MAIN};
            }}
            QMenu::item:selected {{
                background-color: {COLOR_BG_RAISED};
                color: {COLOR_TEXT_MAIN};
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

        act_srt = self.export_menu.addAction("Subtitles (.srt)")
        act_srt.triggered.connect(lambda: self._on_export_format("srt"))

        act_vtt = self.export_menu.addAction("WebVTT (.vtt)")
        act_vtt.triggered.connect(lambda: self._on_export_format("vtt"))

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

        # Shortcuts
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.activated.connect(self._toggle_find_bar)
        self._find_esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.find_bar)
        self._find_esc_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._find_esc_shortcut.activated.connect(self._hide_find_bar)

        # Connect signals
        self.btn_view_raw.clicked.connect(lambda: self._switch_view("raw"))
        self.btn_polish.clicked.connect(self.polish_requested.emit)
        self.btn_view_polished.clicked.connect(lambda: self._switch_view("polished"))
        self.btn_find.clicked.connect(self._toggle_find_bar)
        self.txt_find.textChanged.connect(self._on_find_text_changed)
        self.txt_find.returnPressed.connect(self._find_next)
        self.btn_find_next.clicked.connect(self._find_next)
        self.btn_find_prev.clicked.connect(self._find_prev)
        self.btn_find_close.clicked.connect(self._hide_find_bar)
        self.txt_display.textChanged.connect(self._on_text_changed)
        self.btn_open_folder.clicked.connect(self._open_containing_folder)
        self.btn_copy.clicked.connect(self._copy_text)
        self.btn_clear.clicked.connect(self._on_clear_clicked)

    def _toggle_find_bar(self) -> None:
        if self.find_bar.isVisible():
            self._hide_find_bar()
        else:
            self._show_find_bar()

    def _show_find_bar(self) -> None:
        self.find_bar.setVisible(True)
        self.btn_find.setChecked(True)
        self.txt_find.setFocus()
        self.txt_find.selectAll()
        if self.txt_find.text():
            self._update_find_status(self.txt_find.text())

    def _hide_find_bar(self) -> None:
        self.find_bar.setVisible(False)
        self.btn_find.setChecked(False)
        self.txt_display.setFocus()

    def _on_find_text_changed(self, query: str) -> None:
        if not query:
            self.lbl_find_status.setText("")
            return
        cursor = self.txt_display.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.txt_display.setTextCursor(cursor)
        self.txt_display.find(query)
        self._update_find_status(query)

    def _find_next(self) -> None:
        self._find_match(backward=False)

    def _find_prev(self) -> None:
        self._find_match(backward=True)

    def _find_match(self, backward: bool = False) -> None:
        query = self.txt_find.text()
        if not query:
            self.lbl_find_status.setText("")
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        found = self.txt_display.find(query, flags)
        if not found:
            cursor = self.txt_display.textCursor()
            cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            self.txt_display.setTextCursor(cursor)
            self.txt_display.find(query, flags)
        self._update_find_status(query)

    def _update_find_status(self, query: str) -> None:
        text_lower = self.txt_display.toPlainText().lower()
        q_lower = query.lower()
        positions: list[int] = []
        start = 0
        while True:
            idx = text_lower.find(q_lower, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + max(1, len(q_lower))
        if not positions:
            self.lbl_find_status.setText("0 matches")
            return
        sel_start = self.txt_display.textCursor().selectionStart()
        match_num = positions.index(sel_start) + 1 if sel_start in positions else 1
        self.lbl_find_status.setText(f"{match_num} of {len(positions)}")

    def _on_text_changed(self) -> None:
        if self._updating_text:
            return
        edited = self.txt_display.toPlainText()
        self._exported_paths.clear()
        if self._active_mode == "polished":
            self._polished_text = edited
            if self._current_result is not None:
                self._current_result.polished_text = edited
        else:
            self._raw_edited = True
            self._raw_edited_text = edited
            self._sync_raw_edits(edited)

    def _sync_raw_edits(self, edited: str) -> None:
        lines = [line for line in edited.splitlines() if line.strip()]
        if (
            self._raw_segments
            and len(lines) == len(self._raw_segments)
            and all(line.startswith(seg.formatted_timerange) for line, seg in zip(lines, self._raw_segments))
        ):
            for line, seg in zip(lines, self._raw_segments):
                seg.text = line[len(seg.formatted_timerange):].strip()
            self._raw_segments_stale = False
            clean_full = " ".join(seg.text for seg in self._raw_segments if seg.text)
            if self._current_result is not None:
                self._current_result.segments = self._raw_segments
                self._current_result.full_text = clean_full
        else:
            self._raw_segments_stale = True
            if self._current_result is not None:
                self._current_result.full_text = edited

    def set_status(self, message: str) -> None:
        """Update the status label."""
        self.lbl_status.setText(message)

    def set_progress(self, percent: int, metrics_text: str = "") -> None:
        """Update the progress bar and metrics."""
        self.progress_bar.setValue(max(0, min(100, percent)))
        if metrics_text:
            self.lbl_metrics.setText(metrics_text)

    def append_segment(self, segment: TranscriptSegment) -> None:
        """Append a newly streamed transcription segment."""
        self._raw_segments.append(segment)
        if self._active_mode == "raw":
            self._updating_text = True
            try:
                cursor = self.txt_display.textCursor()
                cursor.movePosition(QTextCursor.End)

                ts_escaped = html.escape(segment.formatted_timerange)
                text_escaped = html.escape(segment.text)
                ts_html = f"<span style='color: {COLOR_PRIMARY}; font-family: monospace; font-weight: 500;'>{ts_escaped}</span>"
                text_html = f" <span style='color: {COLOR_TEXT_MAIN};'>{text_escaped}</span><br>"

                cursor.insertHtml(f"{ts_html}{text_html}")
                self.txt_display.setTextCursor(cursor)
                self.txt_display.ensureCursorVisible()
            finally:
                self._updating_text = False

    def _update_polish_button_state(self) -> None:
        has_raw = bool(
            self._raw_segments
            or (self._current_result and (self._current_result.full_text or "").strip())
            or (self._raw_edited_text and self._raw_edited_text.strip())
        )
        if self._current_result is not None:
            has_polished = bool(
                self._current_result.polished_text and self._current_result.polished_text.strip()
            )
        else:
            has_polished = bool(self._polished_text and self._polished_text.strip())
        self.btn_polish.setEnabled(has_raw)
        self.btn_polish.setText("Re-polish" if has_polished else "Polish")

    def set_polished_text(self, text: str, model_name: str = "") -> None:
        """Store polished text and switch view to it."""
        self._polished_text = text
        self.btn_view_polished.setEnabled(bool(text.strip()))
        if text.strip():
            self.btn_view_polished.setChecked(True)
            self._switch_view("polished")
            info = f"Polished with {model_name}" if model_name else "Polished with LLM"
            self.lbl_view_hint.setText(f"({info})")
        self._update_polish_button_state()

    def _switch_view(self, mode: str) -> None:
        self._active_mode = mode
        self._updating_text = True
        try:
            self.txt_display.clear()

            if mode == "polished" and self._polished_text is not None:
                self.txt_display.setPlainText(self._polished_text)
            elif self._raw_segments_stale and self._raw_edited_text is not None:
                self.txt_display.setPlainText(self._raw_edited_text)
            elif self._raw_segments:
                # Render raw segments
                cursor = self.txt_display.textCursor()
                for seg in self._raw_segments:
                    ts_escaped = html.escape(seg.formatted_timerange)
                    text_escaped = html.escape(seg.text)
                    ts_html = f"<span style='color: {COLOR_PRIMARY}; font-family: monospace; font-weight: 500;'>{ts_escaped}</span>"
                    text_html = f" <span style='color: {COLOR_TEXT_MAIN};'>{text_escaped}</span><br>"
                    cursor.insertHtml(f"{ts_html}{text_html}")
                self.txt_display.setTextCursor(cursor)
            elif self._current_result and self._current_result.full_text:
                self.txt_display.setPlainText(self._current_result.full_text)
        finally:
            self._updating_text = False

    def load_track(
        self,
        track: AudioTrack | None,
        config: TranscriptionConfig | None = None,
    ) -> None:
        """Load a track's transcript, view mode, export state, and status into the viewer."""
        self.clear_view()
        if track is None:
            self.set_status("Idle")
            return

        if track.result is None:
            self._current_track = track
            self._current_config = config
            self.set_status(track.status_message or track.status.value)
            self.set_progress(track.progress_percent)
            return

        result = track.result
        self._raw_segments = list(result.segments)
        self._polished_text = result.polished_text
        self.set_completed_track(track, result, config)

        if result.polished_text and result.polished_text.strip():
            self.set_polished_text(result.polished_text, result.llm_model_used or "")
        else:
            self.btn_view_polished.setEnabled(False)
            self.btn_view_raw.setChecked(True)
            self._switch_view("raw")

        self.set_status(track.status_message or track.status.value)
        self.set_progress(track.progress_percent or 100, track.status_message)

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
        self._update_polish_button_state()

    def set_completed_docx(self, docx_path: Path) -> None:
        """Mark document as ready and enable export/folder actions."""
        self._current_docx_path = docx_path
        self._exported_paths["docx"] = docx_path
        self.btn_export.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        self._update_polish_button_state()

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
        self._raw_edited = False
        self._raw_edited_text = None
        self._raw_segments_stale = False
        self._current_track = None
        self._current_result = None
        self._current_config = None
        self._exported_paths.clear()
        self._current_docx_path = None

        self._updating_text = True
        try:
            self.txt_display.clear()
        finally:
            self._updating_text = False
        self.lbl_find_status.setText("")
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Idle")
        self.lbl_metrics.setText("")
        self.lbl_view_hint.setText("")
        self.btn_view_raw.setChecked(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self._update_polish_button_state()

    def _on_export_format(self, fmt: str) -> None:
        """Export or open the requested format: 'docx', 'pdf', 'md', 'txt', 'srt', 'vtt'."""
        try:
            # 1. Open if already exported and exists
            existing_path = self._exported_paths.get(fmt)
            if existing_path and existing_path.exists():
                success = open_path_in_os(existing_path)
                if success:
                    self.lbl_status.setText(f"Opened {existing_path.name}")
                else:
                    self.lbl_status.setText(f"Saved {existing_path.name}")
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
            if self._current_result is not None:
                result_obj = (
                    replace(self._current_result, segments=[])
                    if self._raw_segments_stale
                    else self._current_result
                )
            else:
                raw_text = (
                    self._raw_edited_text
                    if self._raw_edited and self._raw_edited_text is not None
                    else ("" if self._active_mode == "polished" else self.txt_display.toPlainText())
                )
                result_obj = TranscriptionResult(
                    full_text=raw_text,
                    segments=[] if self._raw_segments_stale else self._raw_segments,
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
                self.lbl_status.setText(f"Exported and opened {saved_path.name}")
            else:
                self.lbl_status.setText(f"Exported to {saved_path.name}")
        except Exception as e:
            self.lbl_status.setText(f"Export error: {e}")

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
                self.lbl_status.setText(f"Directory not found: {p}")
        else:
            self.lbl_status.setText("No output folder available")

    def _copy_text(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_display.toPlainText())
            self.lbl_status.setText("Copied to clipboard")
