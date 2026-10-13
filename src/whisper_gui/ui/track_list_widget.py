"""Track queue widget supporting file picking, drag-and-drop, and status display."""

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

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
}

STATUS_COLORS = {
    TrackStatus.QUEUED: "#6c757d",       # Grey
    TrackStatus.SLICING: "#e67e22",      # Orange
    TrackStatus.TRANSCRIBING: "#2980b9", # Blue
    TrackStatus.COMPLETED: "#27ae60",    # Green
    TrackStatus.CANCELLED: "#8e44ad",    # Purple
    TrackStatus.ERROR: "#c0392b",        # Red
}


class TrackListWidget(QGroupBox):
    """Audio tracks table supporting file selection, drag and drop, and tracking."""

    track_selected = Signal(object)  # Emits AudioTrack or None
    track_count_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Audio Tracks Queue", parent)
        self.setAcceptDrops(True)
        self._tracks: list[AudioTrack] = []
        self._track_map: dict[str, AudioTrack] = {}  # id -> AudioTrack

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 14, 12, 12)

        # Action toolbar
        toolbar = QHBoxLayout()
        self.btn_add_files = QPushButton("➕ Add Audio Files")
        self.btn_add_files.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
        """)
        toolbar.addWidget(self.btn_add_files)

        self.btn_remove = QPushButton("➖ Remove Selected")
        toolbar.addWidget(self.btn_remove)

        self.btn_clear = QPushButton("Clear All")
        toolbar.addWidget(self.btn_clear)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Drop info banner
        self.drop_hint = QLabel("💡 Tip: Drag and drop audio files directly into this area")
        self.drop_hint.setStyleSheet("color: #7f8c8d; font-size: 11px; font-style: italic;")
        layout.addWidget(self.drop_hint)

        # Tracks Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Track Name", "Duration / Slice", "Status", "Word Document (.docx)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                gridline-color: #e9ecef;
            }
            QTableWidget::item:selected {
                background-color: #d4e6f1;
                color: #1a5276;
            }
        """)
        layout.addWidget(self.table)

        # Connect signals
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)
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
        file_paths: list[Path] = []
        for url in urls:
            if url.isLocalFile():
                p = Path(url.toLocalFile()).resolve()
                if p.is_file() and p.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS:
                    file_paths.append(p)

        if file_paths:
            self.add_audio_files(file_paths)
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

    def add_audio_files(self, paths: list[Path]) -> None:
        """Probe and add new audio files to the queue."""
        error_files: list[str] = []
        for p in paths:
            if str(p) in [str(t.file_path) for t in self._tracks]:
                continue  # Already in list

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
                f"Some files could not be loaded:\n" + "\n".join(error_files[:5]),
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
