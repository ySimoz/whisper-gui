"""Track queue widget supporting file/folder picking, drag-and-drop, and status display."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.audio_utils import AudioProbeError, format_seconds, get_audio_info
from whisper_gui.models import AudioTrack, TrackStatus
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
}

STATUS_COLORS = {
    TrackStatus.QUEUED: COLOR_TEXT_MUTED,
    TrackStatus.SLICING: "#F39C12",
    TrackStatus.TRANSCRIBING: COLOR_PRIMARY,
    TrackStatus.COMPLETED: "#2ECC71",
    TrackStatus.CANCELLED: "#E74C3C",
    TrackStatus.ERROR: COLOR_SECONDARY,
}


class TrackListWidget(QGroupBox):
    """Audio tracks table supporting file selection, directory scanning, and drag-and-drop."""

    track_selected = Signal(object)  # Emits AudioTrack or None
    track_count_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Tracks Queue", parent)
        self.setAcceptDrops(True)
        self._tracks: list[AudioTrack] = []
        self._track_map: dict[str, AudioTrack] = {}  # id -> AudioTrack

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 6, 8, 6)

        # Action toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.btn_add_files = QPushButton("Add Files")
        self.btn_add_files.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
                font-weight: bold;
                padding: 4px 12px;
                border: 1px solid {COLOR_PRIMARY};
                border-radius: 4px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
            }}
        """)
        toolbar.addWidget(self.btn_add_files)

        self.btn_add_folder = QPushButton("Add Folder")
        self.btn_add_folder.setToolTip("Scan a directory recursively for all audio files")
        self.btn_add_folder.setStyleSheet("""
            QPushButton {
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 12px;
            }
        """)
        toolbar.addWidget(self.btn_add_folder)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        toolbar.addWidget(self.btn_remove)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        toolbar.addWidget(self.btn_clear)

        toolbar.addStretch()

        self.drop_hint = QLabel("Drag & drop files or folders")
        self.drop_hint.setStyleSheet(f"color: {COLOR_TEXT_HINT}; font-size: 10px;")
        toolbar.addWidget(self.drop_hint)

        layout.addLayout(toolbar)

        # Tracks Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Track Name", "Length / Slice", "Status", "Word Document (.docx)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLOR_BG_INPUT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
                gridline-color: #262D3E;
                font-size: 12px;
                color: {COLOR_TEXT_MAIN};
            }}
            QTableWidget::item:selected {{
                background-color: #243547;
                color: {COLOR_TEXT_MAIN};
            }}
        """)
        layout.addWidget(self.table)

        # Connect signals
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_clear.clicked.connect(self.clear_all)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

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
        ext_filter = "Audio & Video Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.wma *.mp4 *.mkv);;All Files (*)"
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Audio Files for Transcription",
            "",
            ext_filter,
        )
        if files:
            self.add_audio_files([Path(f) for f in files])

    def _on_add_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Audio Files")
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
                "Warning",
                f"Some audio files could not be loaded:\n" + "\n".join(error_files[:5]),
            )

        if self._tracks and self.table.currentRow() == -1:
            self.table.selectRow(0)

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
                range_str = f"Full ({format_seconds(total_dur)})"
            else:
                s = slice_cfg.start_sec
                e = slice_cfg.effective_end(total_dur)
                range_str = f"{format_seconds(s)} → {format_seconds(e)}"
            item_dur = QTableWidgetItem(range_str)
            item_dur.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 1, item_dur)

            # Column 2: Status
            status_text = track.status_message or track.status.value
            item_status = QTableWidgetItem(status_text)
            item_status.setTextAlignment(Qt.AlignCenter)
            color_hex = STATUS_COLORS.get(track.status, "#495057")
            item_status.setForeground(QColor(color_hex))
            self.table.setItem(row, 2, item_status)

            # Column 3: Output Docx
            docx_name = track.effective_docx_path().name
            item_docx = QTableWidgetItem(docx_name)
            item_docx.setToolTip(str(track.effective_docx_path()))
            self.table.setItem(row, 3, item_docx)

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
            range_str = f"Full ({format_seconds(total_dur)})"
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
            item_status.setText(track.status_message or track.status.value)
            color_hex = STATUS_COLORS.get(track.status, "#495057")
            item_status.setForeground(QColor(color_hex))

        # Update Docx column
        item_docx = self.table.item(row, 3)
        if item_docx:
            item_docx.setText(track.effective_docx_path().name)
