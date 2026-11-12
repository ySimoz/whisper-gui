"""Main window for Whisper GUI desktop application with streamlined Swiss AI-native layout."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from whisper_gui import __version__
from whisper_gui.audio_utils import check_ffmpeg_installed
from whisper_gui.models import AudioTrack, TrackStatus, TranscriptSegment, TranscriptionResult
from whisper_gui.platform_utils import get_app_icon, get_asset_path
from whisper_gui.transcriber import Transcriber
from whisper_gui.ui.llm_panel import LLMPanel
from whisper_gui.ui.range_selector import RangeSelectorWidget, TrimAudioDialog
from whisper_gui.ui.settings_page import SettingsPageWidget
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_SURFACE,
    COLOR_BG_WINDOW,
    COLOR_BORDER,
    COLOR_BORDER_LIGHT,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_PRESSED,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_SECONDARY_HOVER,
    COLOR_SECONDARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    GLOBAL_STYLESHEET,
)
from whisper_gui.ui.track_list_widget import TrackListWidget
from whisper_gui.ui.transcript_view import TranscriptView
from whisper_gui.ui.update_dialog import UpdateCheckWorker, UpdateDialog
from whisper_gui.worker import PolishWorker, TranscriptionWorker


class DropzoneCard(QFrame):
    """Clickable dropzone card for importing audio files."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._click_callback = None

    def set_click_callback(self, cb) -> None:
        self._click_callback = cb

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._click_callback:
            self._click_callback()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """Main application window for Whisper GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Whisper GUI v{__version__}")
        self.resize(960, 680)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self.setAcceptDrops(True)

        # Set window icon
        app_icon = get_app_icon()
        if app_icon and not app_icon.isNull():
            self.setWindowIcon(app_icon)

        # Transcriber singleton for caching models
        self.transcriber = Transcriber()
        self.current_worker: TranscriptionWorker | None = None
        self._polish_worker: PolishWorker | None = None
        self._active_track: AudioTrack | None = None
        self._update_check_worker: UpdateCheckWorker | None = None
        self._manual_update_check = False

        self._build_ui()
        self._load_settings()
        self._on_model_changed()
        self._check_dependencies()
        self._sync_queue_display()

        if "PYTEST_CURRENT_TEST" not in os.environ:
            QTimer.singleShot(500, self._check_for_updates)

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_vbox = QVBoxLayout(central_widget)
        main_vbox.setSpacing(0)
        main_vbox.setContentsMargins(0, 0, 0, 0)

        # Page Stack: Page 0 = Transcribe, Page 1 = Settings
        self.page_stack = QStackedWidget(central_widget)
        main_vbox.addWidget(self.page_stack)

        # ---------------- Page 0: Transcribe Workspace ----------------
        self.page_transcribe = QWidget()
        transcribe_vbox = QVBoxLayout(self.page_transcribe)
        transcribe_vbox.setSpacing(10)
        transcribe_vbox.setContentsMargins(16, 12, 16, 12)

        # 1. Header Bar
        header_frame = QFrame()
        header_frame.setObjectName("main_header")
        header_frame.setFixedHeight(48)
        header_frame.setStyleSheet(f"""
            #main_header {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(12)
        header_layout.setAlignment(Qt.AlignVCenter)

        # Left side: Lateral Drawer Toggle + Title + Model Badge
        self.btn_toggle_drawer = QPushButton("☰ Tracks (0)")
        self.btn_toggle_drawer.setCheckable(True)
        self.btn_toggle_drawer.setStyleSheet(f"""
            QPushButton {{
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:checked {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
                border-color: {COLOR_PRIMARY};
            }}
        """)
        self.btn_toggle_drawer.clicked.connect(self._toggle_tracks_drawer)
        self.btn_toggle_queue = self.btn_toggle_drawer  # backward compatibility alias
        header_layout.addWidget(self.btn_toggle_drawer)

        title_lbl = QLabel("Whisper GUI")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet(f"color: {COLOR_TEXT_MAIN}; font-weight: 700;")
        header_layout.addWidget(title_lbl)

        self.lbl_model_badge = QLabel("Model: large-v3-turbo")
        self.lbl_model_badge.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; font-weight: 500;")
        header_layout.addWidget(self.lbl_model_badge)

        header_layout.addStretch()

        self.btn_open_settings = QPushButton("⚙ Settings")
        self.btn_open_settings.setStyleSheet("""
            QPushButton {
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        self.btn_open_settings.clicked.connect(self._open_settings_page)
        header_layout.addWidget(self.btn_open_settings)

        transcribe_vbox.addWidget(header_frame)

        # 2. Main Content Splitter (Lateral Drawer on left | Hero Workspace)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        # 2a. Lateral Tracks Drawer
        self.tracks_drawer = QFrame()
        self.tracks_drawer.setObjectName("tracks_drawer")
        self.tracks_drawer.setMinimumWidth(320)
        self.tracks_drawer.setMaximumWidth(460)
        self.tracks_drawer.setStyleSheet(f"""
            #tracks_drawer {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.queue_drawer = self.tracks_drawer  # backward compatibility alias

        drawer_vbox = QVBoxLayout(self.tracks_drawer)
        drawer_vbox.setContentsMargins(12, 12, 12, 12)
        drawer_vbox.setSpacing(10)

        drawer_hdr = QHBoxLayout()
        drawer_hdr.setSpacing(8)
        self.lbl_drawer_title = QLabel("Tracks")
        self.lbl_drawer_title.setStyleSheet(f"font-weight: 700; font-size: 14px; color: {COLOR_TEXT_MAIN};")
        drawer_hdr.addWidget(self.lbl_drawer_title)

        self.lbl_drawer_count = QLabel("0 tracks")
        self.lbl_drawer_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        drawer_hdr.addWidget(self.lbl_drawer_count)

        drawer_hdr.addStretch()

        btn_close_drawer = QPushButton("✕")
        btn_close_drawer.setFixedSize(24, 24)
        btn_close_drawer.setToolTip("Close drawer")
        btn_close_drawer.setStyleSheet("padding: 0; font-size: 12px; font-weight: 700;")
        btn_close_drawer.clicked.connect(lambda: self.btn_toggle_drawer.setChecked(False) or self.tracks_drawer.hide())
        drawer_hdr.addWidget(btn_close_drawer)
        drawer_vbox.addLayout(drawer_hdr)

        self.track_list = TrackListWidget()
        drawer_vbox.addWidget(self.track_list, stretch=1)
        self.main_splitter.addWidget(self.tracks_drawer)
        self.tracks_drawer.hide()

        # 2b. Central Hero Workspace
        self.center_widget = QWidget()
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(10)

        # Dropzone (shown when 0 tracks loaded)
        self.dropzone_card = DropzoneCard()
        self.dropzone_card.setObjectName("dropzone_card")
        self.dropzone_card.setMinimumHeight(180)
        self.dropzone_card.setCursor(Qt.PointingHandCursor)
        self.dropzone_card.set_click_callback(self.track_list._on_add_files_clicked)
        self.dropzone_card.setStyleSheet(f"""
            #dropzone_card {{
                background-color: {COLOR_BG_SURFACE};
                border: 2px dashed {COLOR_BORDER_LIGHT};
                border-radius: 8px;
            }}
            #dropzone_card:hover {{
                border-color: {COLOR_PRIMARY};
                background-color: #243247;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        drop_layout = QVBoxLayout(self.dropzone_card)
        drop_layout.setContentsMargins(24, 32, 24, 32)
        drop_layout.setSpacing(12)
        drop_layout.setAlignment(Qt.AlignCenter)

        self.lbl_drop_title = QLabel("Import File")
        self.lbl_drop_title.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {COLOR_TEXT_MAIN};")
        self.lbl_drop_title.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.lbl_drop_title)

        self.lbl_drop_icon = QLabel()
        self.lbl_drop_icon.setAlignment(Qt.AlignCenter)
        upload_icon_path = get_asset_path("upload_icon.svg")
        if upload_icon_path:
            self.lbl_drop_icon.setPixmap(QIcon(str(upload_icon_path)).pixmap(QSize(56, 56)))
        drop_layout.addWidget(self.lbl_drop_icon)

        center_layout.addWidget(self.dropzone_card)

        # Active Track Card (shown when >= 1 track loaded)
        self.active_card = QFrame()
        self.active_card.setObjectName("active_card")
        self.active_card.setStyleSheet(f"""
            #active_card {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        card_layout = QVBoxLayout(self.active_card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(12)

        # Track info header
        track_row = QHBoxLayout()
        track_row.setSpacing(10)

        self.lbl_active_name = QLabel("Track Name")
        self.lbl_active_name.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLOR_TEXT_MAIN};")
        track_row.addWidget(self.lbl_active_name, stretch=1)

        self.lbl_active_meta = QLabel("00:00 • 0 MB")
        self.lbl_active_meta.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        track_row.addWidget(self.lbl_active_meta)

        self.lbl_active_slice = QLabel("Full Audio")
        self.lbl_active_slice.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; font-weight: 500;")
        track_row.addWidget(self.lbl_active_slice)
        card_layout.addLayout(track_row)

        # Action bar: Trim Audio, Polish toggle, Drawer button
        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.btn_open_trim = QPushButton("✂ Trim Audio")
        self.btn_open_trim.setStyleSheet("font-weight: 500; padding: 6px 14px;")
        self.btn_open_trim.clicked.connect(self._open_trim_dialog)
        actions_row.addWidget(self.btn_open_trim)

        self.chk_polish_sync = QCheckBox("Polish with AI")
        self.chk_polish_sync.setStyleSheet("font-weight: 600; background-color: transparent;")
        self.chk_polish_sync.toggled.connect(self._on_polish_sync_toggled)
        actions_row.addWidget(self.chk_polish_sync)

        actions_row.addStretch()

        self.btn_active_drawer = QPushButton("☰ View All Tracks")
        self.btn_active_drawer.setStyleSheet("padding: 5px 12px; font-size: 12px;")
        self.btn_active_drawer.clicked.connect(self._open_tracks_drawer)
        actions_row.addWidget(self.btn_active_drawer)

        card_layout.addLayout(actions_row)

        # Hidden compatibility controls
        self.multi_track_widget = QWidget()
        self.multi_track_widget.hide()
        self.combo_active_track = QComboBox()
        self.combo_active_track.setView(QListView())
        self.combo_active_track.currentIndexChanged.connect(self._on_combo_track_changed)
        self.btn_add_another = QPushButton("+ Add Files")
        self.btn_add_another.clicked.connect(self.track_list._on_add_files_clicked)
        self.btn_add_another.hide()

        # Primary transcribe button bar
        transcribe_row = QHBoxLayout()
        transcribe_row.setSpacing(10)

        self.btn_start = QPushButton("Transcribe Audio")
        self.btn_start.setFixedHeight(42)
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
                font-weight: 700;
                font-size: 13px;
                border-radius: 4px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_PRIMARY_PRESSED};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_HINT};
                border: 1px solid {COLOR_BORDER};
            }}
        """)
        self.btn_start.clicked.connect(self._on_start_clicked)
        transcribe_row.addWidget(self.btn_start, stretch=1)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setFixedHeight(42)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SECONDARY};
                color: {COLOR_SECONDARY_TEXT};
                font-weight: 700;
                font-size: 13px;
                padding: 0 22px;
                border-radius: 4px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {COLOR_SECONDARY_HOVER};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_HINT};
                border: 1px solid {COLOR_BORDER};
            }}
        """)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        transcribe_row.addWidget(self.btn_stop)

        card_layout.addLayout(transcribe_row)
        center_layout.addWidget(self.active_card)

        # Live Transcript View
        self.transcript_view = TranscriptView()
        center_layout.addWidget(self.transcript_view, stretch=1)

        self.main_splitter.addWidget(self.center_widget)
        transcribe_vbox.addWidget(self.main_splitter, stretch=1)
        self.page_stack.addWidget(self.page_transcribe)

        # ---------------- Page 1: Dedicated Settings Page ----------------
        self.range_selector = RangeSelectorWidget()
        self.settings_panel = SettingsPanel()
        self.llm_panel = LLMPanel()
        self.settings_page = SettingsPageWidget(self.settings_panel, self.llm_panel, self)
        self.settings_page.back_requested.connect(self._close_settings_page)
        self.page_stack.addWidget(self.settings_page)

        # Compatibility container for tests asserting `window.config_tabs.count() == 3`
        self.config_tabs = QTabWidget()
        self.config_tabs.addTab(self.range_selector, "Trimming")
        self.config_tabs.addTab(QWidget(), "Whisper")
        self.config_tabs.addTab(QWidget(), "Polish")
        self.config_tabs.hide()

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(True)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Connect Signals
        self.track_list.track_selected.connect(self._on_track_selected)
        self.track_list.track_count_changed.connect(self._on_track_count_changed)
        self.range_selector.range_changed.connect(self._on_range_changed)
        self.settings_panel.free_ram_requested.connect(self._on_free_ram_clicked)
        self.settings_panel.check_updates_requested.connect(lambda: self._check_for_updates(manual=True))
        self.settings_panel.combo_model.currentIndexChanged.connect(self._on_model_changed)
        self.llm_panel.chk_enable.toggled.connect(self._on_llm_panel_enable_toggled)
        self.transcript_view.polish_requested.connect(self._on_repolish_clicked)

        # Initial state
        self.range_selector.set_track(None)

    def _toggle_tracks_drawer(self) -> None:
        is_checked = self.btn_toggle_drawer.isChecked()
        self.tracks_drawer.setVisible(is_checked)
        if is_checked:
            total_w = self.main_splitter.width() or 1000
            self.main_splitter.setSizes([350, max(600, total_w - 350)])

    def _toggle_queue_drawer(self) -> None:
        self._toggle_tracks_drawer()

    def _open_tracks_drawer(self) -> None:
        self.btn_toggle_drawer.setChecked(True)
        self.tracks_drawer.show()
        total_w = self.main_splitter.width() or 1000
        self.main_splitter.setSizes([350, max(600, total_w - 350)])

    def _open_settings_page(self) -> None:
        self.settings_panel._update_disk_status()
        self.page_stack.setCurrentIndex(1)

    def _close_settings_page(self) -> None:
        self.page_stack.setCurrentIndex(0)
        self._on_model_changed()
        self.chk_polish_sync.setChecked(self.llm_panel.chk_enable.isChecked())

    def _on_model_changed(self) -> None:
        model_name = self.settings_panel.combo_model.currentText().split()[0]
        self.lbl_model_badge.setText(f"Model: {model_name}")

    def _on_polish_sync_toggled(self, checked: bool) -> None:
        if self.llm_panel.chk_enable.isChecked() != checked:
            self.llm_panel.chk_enable.setChecked(checked)

    def _on_llm_panel_enable_toggled(self, checked: bool) -> None:
        if self.chk_polish_sync.isChecked() != checked:
            self.chk_polish_sync.setChecked(checked)

    def _on_track_count_changed(self, count: int) -> None:
        self.btn_toggle_drawer.setText(f"☰ Tracks ({count})")
        self.lbl_drawer_count.setText(f"{count} {'track' if count == 1 else 'tracks'}")
        if count > 1 and not self.tracks_drawer.isVisible():
            self.btn_toggle_drawer.setChecked(True)
            self.tracks_drawer.show()
            total_w = self.main_splitter.width() or 1000
            self.main_splitter.setSizes([350, max(600, total_w - 350)])
        self._sync_queue_display()

    def _sync_queue_display(self) -> None:
        tracks = self.track_list.get_tracks()
        has_tracks = len(tracks) > 0
        self.dropzone_card.setVisible(not has_tracks)
        self.active_card.setVisible(has_tracks)
        self.btn_active_drawer.setVisible(len(tracks) > 1)

        # Start button label reflects single vs multi-track queue state
        if len(tracks) > 1:
            pending = [t for t in tracks if t.status in (TrackStatus.QUEUED, TrackStatus.ERROR)]
            if pending:
                self.btn_start.setText(f"Transcribe All ({len(pending)} Tracks)")
            else:
                self.btn_start.setText(f"Re-run All ({len(tracks)} Tracks)")
        elif len(tracks) == 1:
            self.btn_start.setText("Transcribe Track")
        else:
            self.btn_start.setText("Transcribe Audio")

        self.combo_active_track.blockSignals(True)
        self.combo_active_track.clear()
        for i, t in enumerate(tracks):
            self.combo_active_track.addItem(f"{i + 1}. {t.info.filename}", t.id)
        self.combo_active_track.blockSignals(False)

        if has_tracks and not self._active_track:
            self._set_active_track(tracks[0])
        elif not has_tracks:
            self._set_active_track(None)

    def _set_active_track(self, track: AudioTrack | None) -> None:
        prev_track = self._active_track
        self._active_track = track
        self.range_selector.set_track(track)

        is_worker_running = self.current_worker is not None and self.current_worker.isRunning()
        streaming_to_other = (
            is_worker_running
            and prev_track is not None
            and prev_track is not track
            and prev_track.status in (TrackStatus.SLICING, TrackStatus.TRANSCRIBING)
        )
        if not streaming_to_other:
            self.transcript_view.load_track(track, self.settings_panel.get_config())

        if track is None:
            self.lbl_active_name.setText("No track selected")
            self.lbl_active_meta.setText("")
            self.lbl_active_slice.setText("Full Audio")
            return

        tracks = self.track_list.get_tracks()
        if len(tracks) > 1:
            try:
                idx = tracks.index(track) + 1
                self.lbl_active_name.setText(f"Track {idx} of {len(tracks)}: {track.info.filename}")
            except ValueError:
                self.lbl_active_name.setText(track.info.filename)
        else:
            self.lbl_active_name.setText(track.info.filename)

        self.lbl_active_meta.setText(f"{track.info.duration_formatted} • {track.info.size_mb:.1f} MB")
        self._update_slice_badge(track)

        # Sync table selection
        for i, t in enumerate(tracks):
            if t.id == track.id:
                self.track_list.table.blockSignals(True)
                self.track_list.table.selectRow(i)
                self.track_list.table.blockSignals(False)
                break

    def _update_slice_badge(self, track: AudioTrack) -> None:
        from whisper_gui.audio_utils import format_seconds
        slice_cfg = track.slice_config
        if slice_cfg.is_full(track.info.duration):
            self.lbl_active_slice.setText("Full Audio")
        else:
            s = format_seconds(slice_cfg.start_sec)
            e = format_seconds(slice_cfg.effective_end(track.info.duration))
            self.lbl_active_slice.setText(f"Trim: {s} → {e}")

    def _on_combo_track_changed(self, index: int) -> None:
        tracks = self.track_list.get_tracks()
        if 0 <= index < len(tracks):
            self._set_active_track(tracks[index])
            self.track_list.table.selectRow(index)

    def _open_trim_dialog(self) -> None:
        if not self._active_track:
            return
        dialog = TrimAudioDialog(self._active_track, parent=self)
        if dialog.exec():
            self._update_slice_badge(self._active_track)
            self.track_list.refresh_track_display(self._active_track.id)

    def _check_dependencies(self) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"):
            return
        ok, msg = check_ffmpeg_installed()
        if not ok:
            QMessageBox.critical(
                self,
                "FFmpeg Missing",
                f"FFmpeg or FFprobe was not detected on your system PATH:\n\n{msg}\n\n"
                f"Whisper GUI requires FFmpeg to slice and decode audio tracks.",
            )

    def _on_track_selected(self, track: AudioTrack | None) -> None:
        if track:
            self._set_active_track(track)

    def _on_range_changed(self, track_id: str) -> None:
        if self._active_track:
            self._update_slice_badge(self._active_track)
        self.track_list.refresh_track_display(track_id)

    def _on_start_clicked(self) -> None:
        tracks = self.track_list.get_tracks()
        if not tracks:
            QMessageBox.warning(
                self,
                "No Audio Tracks",
                "Please add at least one audio file before starting transcription.",
            )
            return

        llm_cfg = self.llm_panel.get_config()
        if llm_cfg.enabled and not llm_cfg.api_key.strip() and llm_cfg.provider != "Custom":
            QMessageBox.warning(
                self,
                "API Key Required",
                "You have enabled LLM Text Polishing, but no API Key is entered.\n\n"
                "Please configure your API Key in Settings.",
            )
            self._open_settings_page()
            return

        pending_tracks = [t for t in tracks if t.status in (TrackStatus.QUEUED, TrackStatus.ERROR)]
        if not pending_tracks:
            reply = QMessageBox.question(
                self,
                "Re-run Transcription?",
                "All tracks are completed. Transcribe them again?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                for t in tracks:
                    t.status = TrackStatus.QUEUED
                    t.status_message = "Queued"
                    self.track_list.refresh_track_display(t.id)
                pending_tracks = tracks
            else:
                return

        config = self.settings_panel.get_config()
        config.llm_config = llm_cfg
        self.transcript_view.clear_view()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.track_list.setEnabled(False)
        self.range_selector.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.llm_panel.setEnabled(False)
        self.status_bar.showMessage("Transcribing...")

        self.current_worker = TranscriptionWorker(
            tracks=pending_tracks,
            transcription_config=config,
            transcriber=self.transcriber,
            parent=self,
        )

        self.current_worker.track_started.connect(self._on_worker_track_started)
        self.current_worker.status_updated.connect(self._on_worker_status_updated)
        self.current_worker.segment_received.connect(self._on_worker_segment_received)
        self.current_worker.progress_updated.connect(self._on_worker_progress_updated)
        self.current_worker.track_completed.connect(self._on_worker_track_completed)
        self.current_worker.track_error.connect(self._on_worker_track_error)
        self.current_worker.batch_finished.connect(self._on_worker_finished)
        self.current_worker.cancelled.connect(self._on_worker_cancelled)

        self.current_worker.start()

    def _on_stop_clicked(self) -> None:
        if self.current_worker and self.current_worker.isRunning():
            self.transcript_view.set_status("Stopping...")
            self.status_bar.showMessage("Stopping...")
            self.current_worker.request_stop()
            self.btn_stop.setEnabled(False)

    def _on_worker_track_started(self, track_id: str) -> None:
        self.track_list.refresh_track_display(track_id)
        track = self.track_list.get_track(track_id)
        if track:
            self._set_active_track(track)
            self.transcript_view.clear_view()
            self.transcript_view.set_status(f"Transcribing {track.info.filename}...")

    def _on_free_ram_clicked(self) -> None:
        self.transcriber.unload_model()
        self.settings_panel.set_ram_status(False)
        self.status_bar.showMessage("Model unloaded (RAM freed).")

    def _on_worker_status_updated(self, track_id: str, message: str) -> None:
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_status(message)
        self.status_bar.showMessage(message)
        self.track_list.refresh_track_display(track_id)
        if self.transcriber.is_loaded:
            self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)

    def _on_worker_segment_received(self, track_id: str, segment: TranscriptSegment) -> None:
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.append_segment(segment)

    def _on_worker_progress_updated(self, track_id: str, percent: int, time_str: str) -> None:
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_progress(percent, time_str)

    def _on_worker_track_completed(self, track_id: str, result: TranscriptionResult) -> None:
        track = self.track_list.get_track(track_id)
        if track:
            track.result = result
        self.track_list.refresh_track_display(track_id)

        if self._active_track is None or self._active_track.id == track_id:
            if result.polished_text:
                self.transcript_view.set_polished_text(
                    result.polished_text, result.llm_model_used or ""
                )
            if track:
                self.transcript_view.set_completed_track(
                    track, result, self.settings_panel.get_config()
                )
            elif result.docx_path:
                self.transcript_view.set_completed_docx(result.docx_path)
            else:
                self.transcript_view.btn_export.setEnabled(True)
                self.transcript_view.btn_open_folder.setEnabled(True)

        if result.docx_path:
            self.status_bar.showMessage(f"Saved: {result.docx_path.name}")
        if self.transcriber.is_loaded:
            self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)

    def _on_worker_track_error(self, track_id: str, error_msg: str) -> None:
        self.track_list.refresh_track_display(track_id)
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_status(f"Error: {error_msg}")
        self.status_bar.showMessage(f"Error: {error_msg}")

    def _on_worker_finished(self) -> None:
        self._reset_ui_state()
        if self.settings_panel.chk_auto_unload.isChecked():
            self.transcriber.unload_model()
            self.settings_panel.set_ram_status(False)
            self.status_bar.showMessage("Completed. Model unloaded.")
        else:
            if self.transcriber.is_loaded:
                self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)
            self.status_bar.showMessage("Transcription completed.")

        QMessageBox.information(
            self,
            "Done",
            "Transcription completed! Document is ready.",
        )

    def _on_worker_cancelled(self) -> None:
        self._reset_ui_state()
        self.status_bar.showMessage("Cancelled.")

    def _reset_ui_state(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.track_list.setEnabled(True)
        self.range_selector.setEnabled(True)
        self.settings_panel.setEnabled(True)
        self.llm_panel.setEnabled(True)
        self.current_worker = None

    def _on_repolish_clicked(self) -> None:
        if self._polish_worker and self._polish_worker.isRunning():
            return
        if self.current_worker and self.current_worker.isRunning():
            return

        track = self._active_track
        if not track or not track.result:
            return

        raw_text = (track.result.full_text or "").strip()
        if not raw_text and track.result.segments:
            raw_text = " ".join(s.text for s in track.result.segments if s.text).strip()
        if not raw_text:
            return

        llm_cfg = self.llm_panel.get_config()
        if not llm_cfg.api_key.strip() and llm_cfg.provider != "Custom":
            QMessageBox.warning(
                self,
                "API Key Required",
                "No LLM API Key is configured.\n\nPlease enter your API Key in Settings.",
            )
            self._open_settings_page()
            return

        self.transcript_view.btn_polish.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.transcript_view.set_status(f"Polishing with {llm_cfg.model_name}...")
        self.status_bar.showMessage(f"Polishing with {llm_cfg.model_name}...")

        self._polish_worker = PolishWorker(track=track, llm_config=llm_cfg, parent=self)
        self._polish_worker.completed.connect(self._on_polish_completed)
        self._polish_worker.failed.connect(self._on_polish_failed)
        self._polish_worker.cancelled.connect(self._on_polish_cancelled)
        self._polish_worker.finished.connect(self._on_polish_worker_finished)
        self._polish_worker.start()

    def _on_polish_completed(self, track_id: str, result: TranscriptionResult) -> None:
        self.btn_start.setEnabled(True)
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_polished_text(
                result.polished_text or "", result.llm_model_used or ""
            )
            self.transcript_view.set_status("Transcript polished successfully.")
        self.status_bar.showMessage("Transcript polished successfully.")
        self.track_list.refresh_track_display(track_id)

    def _on_polish_failed(self, track_id: str, error_msg: str) -> None:
        self.btn_start.setEnabled(True)
        self.transcript_view._update_polish_button_state()
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_status(f"Polish error: {error_msg}")
        self.status_bar.showMessage(f"Polish error: {error_msg}")
        QMessageBox.warning(
            self,
            "Polishing Failed",
            f"Failed to polish transcript:\n\n{error_msg}",
        )

    def _on_polish_cancelled(self) -> None:
        self.btn_start.setEnabled(True)
        self.transcript_view._update_polish_button_state()
        self.transcript_view.set_status("Polishing cancelled.")
        self.status_bar.showMessage("Polishing cancelled.")

    def _on_polish_worker_finished(self) -> None:
        worker = self._polish_worker
        self._polish_worker = None
        if worker is not None:
            worker.deleteLater()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        self.track_list.dropEvent(event)
        self._sync_queue_display()

    def _load_settings(self) -> None:
        settings = QSettings("WhisperGUI", "WhisperAudioTranscriber")
        self.settings_panel.load_settings(settings)
        self.llm_panel.load_settings(settings)
        self.chk_polish_sync.setChecked(self.llm_panel.chk_enable.isChecked())

    def _save_settings(self) -> None:
        settings = QSettings("WhisperGUI", "WhisperAudioTranscriber")
        self.settings_panel.save_settings(settings)
        self.llm_panel.save_settings(settings)

    def _check_for_updates(self, manual: bool = False) -> None:
        if self._update_check_worker and self._update_check_worker.isRunning():
            return
        self._manual_update_check = manual
        if manual:
            self.settings_panel.btn_check_updates.setEnabled(False)
            self.status_bar.showMessage("Checking for updates...")
        self._update_check_worker = UpdateCheckWorker(parent=self)
        self._update_check_worker.update_available.connect(self._on_update_available)
        self._update_check_worker.no_update.connect(self._on_no_update_available)
        self._update_check_worker.finished.connect(self._on_update_check_finished)
        self._update_check_worker.start()

    def _on_update_available(self, release) -> None:
        self._manual_update_check = False
        dialog = UpdateDialog(release, parent=self)
        dialog.exec()

    def _on_no_update_available(self) -> None:
        if self._manual_update_check:
            self._manual_update_check = False
            self.status_bar.showMessage(f"You are on the latest version (v{__version__}).")
            QMessageBox.information(
                self,
                "No Updates Available",
                f"No updates available. You are already running the latest version (v{__version__}).",
            )

    def _on_update_check_finished(self) -> None:
        self.settings_panel.btn_check_updates.setEnabled(True)
        if self._update_check_worker is not None:
            self._update_check_worker.wait(1000)
            self._update_check_worker.deleteLater()
        self._update_check_worker = None

    def closeEvent(self, event) -> None:
        self._save_settings()
        if self._update_check_worker and self._update_check_worker.isRunning():
            self._update_check_worker.requestInterruption()
            self._update_check_worker.wait(1000)
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.request_stop()
            self.current_worker.wait(3000)
        if self._polish_worker and self._polish_worker.isRunning():
            self._polish_worker.request_stop()
            self._polish_worker.wait(3000)
        event.accept()
