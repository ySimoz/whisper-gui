"""Track queue widget supporting file/folder picking, drag-and-drop, and status display."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
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


class TrackListWidget(QFrame):
    """Audio tracks table supporting file selection, directory scanning, and drag-and-drop."""

    track_selected = Signal(object)  # Emits AudioTrack or None
    track_count_changed = Signal(int)
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

        # Action toolbar
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

        self.btn_remove = QPushButton(tr("tracks.remove"))
        self.btn_remove.setFixedHeight(32)
        self.btn_remove.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        toolbar.addWidget(self.btn_remove)

        self.btn_clear = QPushButton(tr("tracks.clear"))
        self.btn_clear.setFixedHeight(32)
        self.btn_clear.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        toolbar.addWidget(self.btn_clear)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Tracks Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("tracks.col_track"),
            tr("tracks.col_length"),
            tr("tracks.col_status"),
            tr("tracks.col_docx"),
        ])
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(76)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(2, 108)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setColumnHidden(3, True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.table, stretch=1)

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
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_clear.clicked.connect(self.clear_all)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        self.btn_add_files.setText(tr("tracks.add_files"))
        self.btn_add_folder.setText(tr("tracks.add_folder"))
        self.btn_add_folder.setToolTip(tr("tracks.add_folder_tooltip"))
        self.btn_remove.setText(tr("tracks.remove"))
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
        """Apply the active palette to the queue table and status colors."""
        p = get_palette()
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {p.bg_input};
                alternate-background-color: {p.bg_panel_alt};
                border: 1px solid {p.border};
                border-radius: 8px;
                font-size: 12px;
                color: {p.text_main};
            }}
            QTableWidget::item {{
                border-bottom: 1px solid {p.border};
                padding: 4px 12px;
            }}
            QTableWidget::item:selected {{
                background-color: {p.bg_raised};
                color: {p.text_main};
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
        # Expand directories to find all contained audio files
        resolved_files: list[Path] = []
        for p in paths:
            p = Path(p).resolve()
            if p.is_dir():
                for ext in SUPPORTED_AUDIO_EXTENSIONS:
                    resolved_files.extend(p.rglob(f"*{ext}"))
                    resolved_files.extend(p.rglob(f"*{ext.upper()}"))
            elif p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                resolved_files.append(p)

        # Deduplicate preserving order
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
            # Column 0: Track Name
            item_name = QTableWidgetItem(track.info.filename)
            item_name.setToolTip(str(track.file_path))
            self.table.setItem(row, 0, item_name)

            # Column 1: Duration & Range
            total_dur = track.info.duration
            slice_cfg = track.slice_config
            if slice_cfg.is_full(total_dur):
                range_str = tr("tracks.range_full", duration=format_seconds(total_dur))
            else:
                s = slice_cfg.start_sec
                e = slice_cfg.effective_end(total_dur)
                range_str = f"{format_seconds(s)} → {format_seconds(e)}"
            item_dur = QTableWidgetItem(range_str)
            item_dur.setFont(fixed_mono_font(11))
            item_dur.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, item_dur)

            # Column 2: Status
            status_text = display_track_status(track.status_message, track.status)
            item_status = QTableWidgetItem(status_text)
            item_status.setToolTip(status_text)
            item_status.setTextAlignment(Qt.AlignCenter)
            item_status.setForeground(QColor(_status_color(track.status)))
            self.table.setItem(row, 2, item_status)

            # Column 3: Output Docx
            docx_name = track.effective_docx_path().name
            item_docx = QTableWidgetItem(docx_name)
            item_docx.setToolTip(str(track.effective_docx_path()))
            self.table.setItem(row, 3, item_docx)
        self._update_export_all_state()

    def _on_selection_changed(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._tracks):
            self.track_selected.emit(self._tracks[row])
        else:
            self.track_selected.emit(None)

    def _on_remove_clicked(self) -> None:
        row = self.table.currentRow()
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
        """Update display for a single track whose slice config or status changed."""
        track = self._track_map.get(track_id)
        if not track:
            return
        try:
            row = self._tracks.index(track)
        except ValueError:
            return

        # Update Range column
        total_dur = track.info.duration
        slice_cfg = track.slice_config
        if slice_cfg.is_full(total_dur):
            range_str = tr("tracks.range_full", duration=format_seconds(total_dur))
        else:
            s = slice_cfg.start_sec
            e = slice_cfg.effective_end(total_dur)
            range_str = f"{format_seconds(s)} → {format_seconds(e)}"

        item_dur = self.table.item(row, 1)
        if item_dur:
            item_dur.setText(range_str)

        # Update Status column
        item_status = self.table.item(row, 2)
        if item_status:
            status_text = display_track_status(track.status_message, track.status)
            item_status.setText(status_text)
            item_status.setToolTip(status_text)
            item_status.setForeground(QColor(_status_color(track.status)))

        # Update Docx column
        item_docx = self.table.item(row, 3)
        if item_docx:
            item_docx.setText(track.effective_docx_path().name)
        self._update_export_all_state()
