"""Track queue widget supporting file/folder picking, drag-and-drop, and right-click actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.audio_utils import AudioProbeError, format_seconds, get_audio_info
from whisper_gui.i18n import display_track_status, tr
from whisper_gui.models import AudioTrack, TrackStatus
from whisper_gui.ui.theme import (
    fixed_mono_font,
    get_palette,
    load_ui_icon,
    menu_stylesheet,
    style_menu,
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
}


def _status_color(status: TrackStatus) -> str:
    p = get_palette()
    mapping = {
        TrackStatus.QUEUED: p.text_muted,
        TrackStatus.SLICING: p.warning,
        TrackStatus.TRANSCRIBING: p.primary,
        TrackStatus.COMPLETED: p.positive,
        TrackStatus.CANCELLED: p.negative,
        TrackStatus.ERROR: p.negative,
    }
    return mapping.get(status, p.text_muted)


def _format_track_range(track: AudioTrack) -> str:
    total_dur = track.info.duration
    slice_cfg = track.slice_config
    if slice_cfg.is_full(total_dur):
        return tr("tracks.range_full", duration=format_seconds(total_dur))
    s = slice_cfg.start_sec
    e = slice_cfg.effective_end(total_dur)
    return f"{format_seconds(s)} → {format_seconds(e)}"


class _TrackRowDelegate(QStyledItemDelegate):
    """Paints hierarchical two-line track rows without nested table borders."""

    ROW_HEIGHT = 56

    def __init__(self, list_widget: TrackListWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._widget = list_widget

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(max(120, option.rect.width()), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        track = self._widget.track_at_row(index.row())
        if track is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        p = get_palette()
        row = index.row()
        is_selected = bool(option.state & QStyle.State.State_Selected)
        is_hovered = bool(option.state & QStyle.State.State_MouseOver)
        selected_row = self._widget.table.currentRow()
        card_rect = QRectF(option.rect).adjusted(0.5, 2.5, -0.5, -2.5)

        if is_selected:
            painter.setBrush(QColor(p.bg_raised))
            painter.setPen(QPen(QColor(p.border_light), 1.0))
            painter.drawRoundedRect(card_rect, 8.0, 8.0)

            accent_rect = QRectF(
                card_rect.left() + 5.0,
                card_rect.top() + 10.0,
                3.0,
                max(8.0, card_rect.height() - 20.0),
            )
            painter.setBrush(QColor(p.primary))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(accent_rect, 1.5, 1.5)
        elif is_hovered:
            painter.setBrush(QColor(p.bg_panel_alt))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(card_rect, 8.0, 8.0)
        elif row < self._widget.table.rowCount() - 1 and row != selected_row - 1:
            painter.setPen(QPen(QColor(p.border), 1.0))
            y = option.rect.bottom()
            painter.drawLine(option.rect.left() + 8, y, option.rect.right() - 8, y)

        left_x = option.rect.left() + 16
        right_x = option.rect.right() - 12
        content_w = max(48, right_x - left_x)

        # Line 1: primary track filename
        title_font = QFont(option.font)
        title_font.setPixelSize(13)
        title_font.setWeight(QFont.Weight.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor(p.text_main))
        title_fm = QFontMetrics(title_font)
        elided_title = title_fm.elidedText(track.info.filename, Qt.TextElideMode.ElideMiddle, content_w)
        painter.drawText(
            QRect(left_x, option.rect.top() + 8, content_w, 20),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_title,
        )

        # Line 2: mono range metadata (left) + status dot and text (right)
        range_text = _format_track_range(track)
        mono_font = fixed_mono_font(11)
        dur_fm = QFontMetrics(mono_font)

        status_text = display_track_status(track.status_message, track.status)
        status_font = QFont(option.font)
        status_font.setPixelSize(11)
        status_font.setWeight(QFont.Weight.Medium)
        status_fm = QFontMetrics(status_font)
        status_color = QColor(_status_color(track.status))

        dot_d = 6.0
        dot_gap = 6
        dur_w = dur_fm.horizontalAdvance(range_text)
        max_status_w = max(56, content_w - min(dur_w, content_w // 2) - int(dot_d) - dot_gap - 12)
        elided_status = status_fm.elidedText(status_text, Qt.TextElideMode.ElideRight, max_status_w)
        status_draw_w = status_fm.horizontalAdvance(elided_status)

        line2_top = option.rect.top() + 30
        max_dur_w = max(32, content_w - status_draw_w - int(dot_d) - dot_gap - 12)
        elided_dur = dur_fm.elidedText(range_text, Qt.TextElideMode.ElideRight, max_dur_w)

        painter.setFont(mono_font)
        painter.setPen(QColor(p.text_muted))
        painter.drawText(
            QRect(left_x, line2_top, max_dur_w, 18),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_dur,
        )

        dot_x = right_x - status_draw_w - dot_gap - dot_d
        dot_y = line2_top + (18.0 - dot_d) / 2.0
        painter.setBrush(status_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(dot_x, dot_y, dot_d, dot_d))

        painter.setFont(status_font)
        painter.setPen(status_color)
        painter.drawText(
            QRect(right_x - status_draw_w, line2_top, status_draw_w, 18),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            elided_status,
        )

        painter.restore()


class TrackListWidget(QFrame):
    """Audio tracks queue supporting file/folder import, drag-and-drop, and right-click actions."""

    track_selected = Signal(object)  # Emits AudioTrack or None
    track_count_changed = Signal(int)
    track_renamed = Signal(object)  # Emits AudioTrack
    export_all_requested = Signal(str, object)  # format_name ("docx", ..., or ""), target_dir (Path | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._tracks: list[AudioTrack] = []
        self._track_map: dict[str, AudioTrack] = {}  # id -> AudioTrack

        self.setObjectName("track_list_frame")
        self.setStyleSheet("""
            #track_list_frame {
                background: transparent;
                border: none;
            }
        """)

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Action toolbar: plain-text Add actions left, quiet ghost Clear right
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_add_files = QPushButton(tr("tracks.add_files"))
        self.btn_add_files.setFixedHeight(32)
        self.btn_add_files.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        toolbar.addWidget(self.btn_add_files)

        self.btn_add_folder = QPushButton(tr("tracks.add_folder"))
        self.btn_add_folder.setFixedHeight(32)
        self.btn_add_folder.setToolTip(tr("tracks.add_folder_tooltip"))
        self.btn_add_folder.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        toolbar.addWidget(self.btn_add_folder)

        toolbar.addStretch()

        self.btn_clear = QPushButton(tr("tracks.clear"))
        self.btn_clear.setObjectName("btn_tracks_clear")
        self.btn_clear.setFixedHeight(32)
        self.btn_clear.setEnabled(False)
        toolbar.addWidget(self.btn_clear)
        layout.addLayout(toolbar)

        self.toolbar_divider = QFrame()
        self.toolbar_divider.setFrameShape(QFrame.Shape.HLine)
        self.toolbar_divider.setFixedHeight(1)
        layout.addWidget(self.toolbar_divider)

        # Single-column borderless track list backed by QTableWidget for API compatibility
        self.table = QTableWidget()
        self.table.setObjectName("track_queue_table")
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("tracks.col_track"),
            tr("tracks.col_length"),
            tr("tracks.col_status"),
            tr("tracks.col_docx"),
        ])
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setVisible(False)
        self.table.setColumnHidden(1, True)
        self.table.setColumnHidden(2, True)
        self.table.setColumnHidden(3, True)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setMouseTracking(True)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(_TrackRowDelegate.ROW_HEIGHT)
        self.table.setItemDelegateForColumn(0, _TrackRowDelegate(self, self.table))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table, stretch=1)

        self.footer_divider = QFrame()
        self.footer_divider.setFrameShape(QFrame.Shape.HLine)
        self.footer_divider.setFixedHeight(1)
        layout.addWidget(self.footer_divider)

        # Drawer footer: batch export action for completed tracks
        footer = QHBoxLayout()
        footer.setSpacing(8)

        self.btn_export_all = QPushButton(tr("tracks.export_all"))
        self.btn_export_all.setIconSize(QSize(16, 16))
        self.btn_export_all.setFixedHeight(32)
        self.btn_export_all.setEnabled(False)

        self.export_all_menu = style_menu(QMenu(self))
        self._act_all_docx = self.export_all_menu.addAction(tr("transcript.menu_docx"))
        self._act_all_docx.triggered.connect(lambda: self.export_all_requested.emit("docx", None))
        self._act_all_pdf = self.export_all_menu.addAction(tr("transcript.menu_pdf"))
        self._act_all_pdf.triggered.connect(lambda: self.export_all_requested.emit("pdf", None))
        self._act_all_md = self.export_all_menu.addAction(tr("transcript.menu_md"))
        self._act_all_md.triggered.connect(lambda: self.export_all_requested.emit("md", None))
        self._act_all_txt = self.export_all_menu.addAction(tr("transcript.menu_txt"))
        self._act_all_txt.triggered.connect(lambda: self.export_all_requested.emit("txt", None))
        self._act_all_srt = self.export_all_menu.addAction(tr("transcript.menu_srt"))
        self._act_all_srt.triggered.connect(lambda: self.export_all_requested.emit("srt", None))
        self._act_all_vtt = self.export_all_menu.addAction(tr("transcript.menu_vtt"))
        self._act_all_vtt.triggered.connect(lambda: self.export_all_requested.emit("vtt", None))
        self.export_all_menu.addSeparator()
        self._act_all_folder = self.export_all_menu.addAction(tr("tracks.export_all_folder"))
        self._act_all_folder.triggered.connect(self._on_export_all_to_folder_clicked)

        self.btn_export_all.setMenu(self.export_all_menu)
        footer.addWidget(self.btn_export_all, stretch=1)
        layout.addLayout(footer)

        self.apply_theme()

        # Connect signals
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        self.btn_clear.clicked.connect(self.clear_all)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)

    def track_at_row(self, row: int) -> AudioTrack | None:
        """Return the track at the given table row, if valid."""
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        self.btn_add_files.setText(tr("tracks.add_files"))
        self.btn_add_folder.setText(tr("tracks.add_folder"))
        self.btn_add_folder.setToolTip(tr("tracks.add_folder_tooltip"))
        self.btn_clear.setText(tr("tracks.clear"))
        self.table.setHorizontalHeaderLabels([
            tr("tracks.col_track"),
            tr("tracks.col_length"),
            tr("tracks.col_status"),
            tr("tracks.col_docx"),
        ])
        self._act_all_docx.setText(tr("transcript.menu_docx"))
        self._act_all_pdf.setText(tr("transcript.menu_pdf"))
        self._act_all_md.setText(tr("transcript.menu_md"))
        self._act_all_txt.setText(tr("transcript.menu_txt"))
        self._act_all_srt.setText(tr("transcript.menu_srt"))
        self._act_all_vtt.setText(tr("transcript.menu_vtt"))
        self._act_all_folder.setText(tr("tracks.export_all_folder"))
        current_row = self.table.currentRow()
        self.table.blockSignals(True)
        self._refresh_table()
        if 0 <= current_row < self.table.rowCount():
            self.table.selectRow(current_row)
        self.table.blockSignals(False)
        self._update_export_all_state()

    def apply_theme(self) -> None:
        """Apply the active palette to the drawer list, dividers, and status colors."""
        p = get_palette()
        divider_style = f"background-color: {p.border}; border: none;"
        self.toolbar_divider.setStyleSheet(divider_style)
        self.footer_divider.setStyleSheet(divider_style)

        self.btn_clear.setStyleSheet(f"""
            QPushButton#btn_tracks_clear {{
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 12px;
                color: {p.text_muted};
            }}
            QPushButton#btn_tracks_clear:hover {{
                background-color: {p.bg_raised};
                color: {p.text_main};
            }}
            QPushButton#btn_tracks_clear:disabled {{
                color: {p.text_hint};
            }}
        """)

        self.table.setStyleSheet(f"""
            QTableWidget#track_queue_table {{
                background-color: transparent;
                border: none;
                outline: none;
            }}
            QTableWidget#track_queue_table QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 4px 0px;
            }}
            QTableWidget#track_queue_table QScrollBar::handle:vertical {{
                background: {p.border_light};
                min-height: 24px;
                border-radius: 3px;
            }}
            QTableWidget#track_queue_table QScrollBar::handle:vertical:hover {{
                background: {p.text_muted};
            }}
            QTableWidget#track_queue_table QScrollBar::add-line:vertical,
            QTableWidget#track_queue_table QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self.btn_export_all.setIcon(load_ui_icon("export"))
        self.btn_export_all.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 24px 4px 12px;
            }}
            QPushButton::menu-indicator {{
                image: url({p.chevron_url});
                subcontrol-origin: padding;
                subcontrol-position: right center;
                right: 8px;
                width: 12px;
                height: 12px;
            }}
        """)
        self.export_all_menu.setStyleSheet(menu_stylesheet(p))
        for row, track in enumerate(self._tracks):
            item_status = self.table.item(row, 2)
            if item_status is not None:
                item_status.setForeground(QColor(_status_color(track.status)))
        self.table.viewport().update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        paths: list[Path] = []
        for url in urls:
            if url.isLocalFile():
                p = Path(url.toLocalFile()).resolve()
                paths.append(p)

        if paths:
            self.add_audio_files(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _on_add_files_clicked(self) -> None:
        ext_filter = tr("tracks.file_filter")
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("tracks.select_files_title"),
            "",
            ext_filter,
        )
        if files:
            self.add_audio_files([Path(f) for f in files])

    def _on_add_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("tracks.select_folder_title"))
        if folder:
            self.add_audio_files([Path(folder)])

    def add_audio_files(self, paths: list[Path]) -> None:
        """Probe and add new audio files to the queue, scanning directories recursively."""
        resolved_files: list[Path] = []
        for p in paths:
            p = Path(p).resolve()
            if p.is_dir():
                for ext in SUPPORTED_AUDIO_EXTENSIONS:
                    resolved_files.extend(p.rglob(f"*{ext}"))
                    resolved_files.extend(p.rglob(f"*{ext.upper()}"))
            elif p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                resolved_files.append(p)

        unique_files: list[Path] = []
        for f in resolved_files:
            if f not in unique_files:
                unique_files.append(f)

        error_files: list[str] = []
        for p in unique_files:
            if str(p) in [str(t.file_path) for t in self._tracks]:
                continue  # Already in queue

            try:
                info = get_audio_info(p)
                track = AudioTrack(p, info)
                self._tracks.append(track)
                self._track_map[track.id] = track
            except AudioProbeError as exc:
                error_files.append(f"{p.name}: {exc}")

        self._refresh_table()
        self.track_count_changed.emit(len(self._tracks))

        if error_files:
            QMessageBox.warning(
                self,
                tr("tracks.warn_title"),
                tr("tracks.warn_load_body", errors="\n".join(error_files[:5])),
            )

        if self._tracks and self.table.currentRow() == -1:
            self.table.selectRow(0)

    def add_existing_track(self, track: AudioTrack, select: bool = True) -> AudioTrack:
        """Add or focus a pre-built AudioTrack (e.g., reopened from history)."""
        for idx, existing in enumerate(self._tracks):
            if (track.history_id and existing.history_id == track.history_id) or (
                existing.file_path == track.file_path and existing.status == track.status
            ):
                if select:
                    self.table.selectRow(idx)
                return existing

        self._tracks.append(track)
        self._track_map[track.id] = track
        self._refresh_table()
        self.track_count_changed.emit(len(self._tracks))
        if select:
            self.table.selectRow(len(self._tracks) - 1)
        return track

    def _on_export_all_to_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("tracks.select_export_folder_title"))
        if folder:
            self.export_all_requested.emit("", Path(folder).resolve())

    def _update_export_all_state(self) -> None:
        self.btn_clear.setEnabled(len(self._tracks) > 0)
        completed_count = sum(
            1
            for t in self._tracks
            if t.status == TrackStatus.COMPLETED and t.result is not None
        )
        self.btn_export_all.setEnabled(completed_count > 0)
        if completed_count > 0:
            self.btn_export_all.setText(tr("tracks.export_all_count", count=completed_count))
        else:
            self.btn_export_all.setText(tr("tracks.export_all"))

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._tracks))
        for row, track in enumerate(self._tracks):
            item_name = QTableWidgetItem(track.info.filename)
            item_name.setToolTip(str(track.file_path))
            self.table.setItem(row, 0, item_name)

            range_str = _format_track_range(track)
            item_dur = QTableWidgetItem(range_str)
            item_dur.setFont(fixed_mono_font(11))
            self.table.setItem(row, 1, item_dur)

            status_text = display_track_status(track.status_message, track.status)
            item_status = QTableWidgetItem(status_text)
            item_status.setToolTip(status_text)
            item_status.setForeground(QColor(_status_color(track.status)))
            self.table.setItem(row, 2, item_status)

            docx_name = track.effective_docx_path().name
            item_docx = QTableWidgetItem(docx_name)
            item_docx.setToolTip(str(track.effective_docx_path()))
            self.table.setItem(row, 3, item_docx)
        self._update_export_all_state()
        self.table.viewport().update()

    def _on_selection_changed(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            self.track_selected.emit(self._tracks[row])
        else:
            self.track_selected.emit(None)
        self.table.viewport().update()

    def build_context_menu(self, row: int) -> QMenu | None:
        """Build the context menu for the track at `row`, or None if invalid."""
        if not (0 <= row < len(self._tracks)):
            return None
        p = get_palette()
        menu = style_menu(QMenu(self))
        menu.setStyleSheet(menu_stylesheet(p))
        act_rename = menu.addAction(tr("tracks.ctx_rename"))
        act_rename.triggered.connect(lambda: self._rename_track_at(row))
        act_remove = menu.addAction(tr("tracks.ctx_remove"))
        act_remove.triggered.connect(lambda: self.remove_track_at(row))
        return menu

    def _on_table_context_menu(self, pos: QPoint) -> None:
        row = self.table.indexAt(pos).row()
        if not (0 <= row < len(self._tracks)):
            return
        self.table.selectRow(row)
        menu = self.build_context_menu(row)
        if menu is not None:
            menu.exec(self.table.viewport().mapToGlobal(pos))

    def _prompt_track_name(self, track: AudioTrack) -> tuple[str, bool]:
        return QInputDialog.getText(
            self,
            tr("tracks.rename_title"),
            tr("tracks.rename_label"),
            text=track.info.filename,
        )

    def _rename_track_at(self, row: int) -> bool:
        track = self.track_at_row(row)
        if track is None:
            return False
        new_name, ok = self._prompt_track_name(track)
        cleaned = new_name.strip() if ok else ""
        if not ok or not cleaned or cleaned == track.info.filename:
            return False
        track.info.filename = cleaned
        self.refresh_track_display(track.id)
        self.track_renamed.emit(track)
        return True

    def remove_track_at(self, row: int) -> None:
        """Remove the track at `row` and update selection cleanly."""
        if 0 <= row < len(self._tracks):
            track = self._tracks.pop(row)
            self._track_map.pop(track.id, None)
            self._refresh_table()
            self.track_count_changed.emit(len(self._tracks))
            if self._tracks:
                new_row = min(row, len(self._tracks) - 1)
                self.table.selectRow(new_row)
            else:
                self.track_selected.emit(None)

    def _on_remove_clicked(self) -> None:
        self.remove_track_at(self.table.currentRow())

    def clear_all(self) -> None:
        self._tracks.clear()
        self._track_map.clear()
        self._refresh_table()
        self.track_count_changed.emit(0)
        self.track_selected.emit(None)

    def get_tracks(self) -> list[AudioTrack]:
        return list(self._tracks)

    def get_track(self, track_id: str) -> AudioTrack | None:
        """Retrieve an AudioTrack by its unique identifier."""
        return self._track_map.get(track_id)

    def get_selected_track(self) -> AudioTrack | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    def refresh_track_display(self, track_id: str) -> None:
        """Update display for a single track whose metadata, slice config, or status changed."""
        track = self._track_map.get(track_id)
        if not track:
            return
        try:
            row = self._tracks.index(track)
        except ValueError:
            return

        item_name = self.table.item(row, 0)
        if item_name:
            item_name.setText(track.info.filename)

        item_dur = self.table.item(row, 1)
        if item_dur:
            item_dur.setText(_format_track_range(track))

        item_status = self.table.item(row, 2)
        if item_status:
            status_text = display_track_status(track.status_message, track.status)
            item_status.setText(status_text)
            item_status.setToolTip(status_text)
            item_status.setForeground(QColor(_status_color(track.status)))

        item_docx = self.table.item(row, 3)
        if item_docx:
            item_docx.setText(track.effective_docx_path().name)
        self._update_export_all_state()
        self.table.viewport().update()
