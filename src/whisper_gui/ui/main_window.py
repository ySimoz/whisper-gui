"""Main window for Whisper GUI desktop application with responsive layouts and vibrant dark theme."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from whisper_gui import __version__
from whisper_gui.audio_utils import check_ffmpeg_installed
from whisper_gui.models import AudioTrack, TrackStatus, TranscriptSegment, TranscriptionResult
from whisper_gui.transcriber import Transcriber
from whisper_gui.ui.llm_panel import LLMPanel
from whisper_gui.ui.range_selector import RangeSelectorWidget
from whisper_gui.ui.settings_panel import SettingsPanel
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
    GLOBAL_STYLESHEET,
)
from whisper_gui.ui.track_list_widget import TrackListWidget
from whisper_gui.ui.transcript_view import TranscriptView
from whisper_gui.worker import TranscriptionWorker


class MainWindow(QMainWindow):
    """Main application window for Whisper GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Whisper GUI - Audio Transcription & Docx Export v{__version__}")
        self.resize(1120, 740)
        self.setMinimumSize(780, 500)
        self.setStyleSheet(GLOBAL_STYLESHEET)

        # Transcriber singleton for caching models
        self.transcriber = Transcriber()
        self.current_worker: TranscriptionWorker | None = None

        self._build_ui()
        self._load_settings()
        self._check_dependencies()

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_vbox = QVBoxLayout(central_widget)
        main_vbox.setSpacing(8)
        main_vbox.setContentsMargins(10, 10, 10, 6)

        # Header bar
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.StyledPanel)
        header_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_BG_SURFACE};
                border: 1px solid {COLOR_BORDER};
                border-radius: 6px;
            }}
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(10)

        title_lbl = QLabel()
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setTextFormat(Qt.RichText)
        title_lbl.setText(
            f"<span style='color: {COLOR_PRIMARY}; font-weight: bold;'>Whisper</span> "
            f"<span style='color: {COLOR_SECONDARY}; font-weight: bold;'>Transcriber</span>"
        )
        header_layout.addWidget(title_lbl)

        header_layout.addStretch()

        # Primary Action Buttons
        self.btn_start = QPushButton("Start Transcription")
        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_PRIMARY_TEXT};
                font-weight: bold;
                font-size: 12px;
                padding: 6px 18px;
                border: 1px solid {COLOR_PRIMARY};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_PRIMARY_HOVER};
            }}
            QPushButton:disabled {{
                background-color: {COLOR_BG_INPUT};
                color: {COLOR_TEXT_HINT};
                border: 1px solid {COLOR_BORDER};
            }}
        """)
        header_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLOR_SECONDARY};
                color: {COLOR_SECONDARY_TEXT};
                font-weight: bold;
                font-size: 12px;
                padding: 6px 18px;
                border: 1px solid {COLOR_SECONDARY};
                border-radius: 4px;
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
        header_layout.addWidget(self.btn_stop)

        main_vbox.addWidget(header_frame)

        # Main horizontal splitter: Left = Track Queue, Right = Slicing/Settings + Transcript
        self.h_splitter = QSplitter(Qt.Horizontal)
        self.h_splitter.setChildrenCollapsible(False)

        # Left pane: Track list
        self.track_list = TrackListWidget()
        self.h_splitter.addWidget(self.track_list)

        # Right pane: Vertical splitter with Tabs on top and Live Transcript below
        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.setChildrenCollapsible(False)

        # Configuration Tabs
        self.config_tabs = QTabWidget()

        # Tab 1: Range Selector in scroll area
        self.range_selector = RangeSelectorWidget()
        scroll_range = QScrollArea()
        scroll_range.setWidgetResizable(True)
        scroll_range.setFrameShape(QFrame.NoFrame)
        scroll_range.setWidget(self.range_selector)
        self.config_tabs.addTab(scroll_range, "Audio Trimming")

        # Tab 2: Settings Panel in scroll area
        self.settings_panel = SettingsPanel()
        scroll_settings = QScrollArea()
        scroll_settings.setWidgetResizable(True)
        scroll_settings.setFrameShape(QFrame.NoFrame)
        scroll_settings.setWidget(self.settings_panel)
        self.config_tabs.addTab(scroll_settings, "Whisper Settings")

        # Tab 3: LLM Text Polish Panel in scroll area
        self.llm_panel = LLMPanel()
        scroll_llm = QScrollArea()
        scroll_llm.setWidgetResizable(True)
        scroll_llm.setFrameShape(QFrame.NoFrame)
        scroll_llm.setWidget(self.llm_panel)
        self.config_tabs.addTab(scroll_llm, "Text Polish")

        self.v_splitter.addWidget(self.config_tabs)

        # Bottom of right pane: Live Transcript & Export view
        self.transcript_view = TranscriptView()
        self.v_splitter.addWidget(self.transcript_view)

        # Proportion settings: config tabs compact, transcript view gets majority of room
        self.v_splitter.setStretchFactor(0, 0)
        self.v_splitter.setStretchFactor(1, 1)
        self.v_splitter.setSizes([120, 520])

        self.h_splitter.addWidget(self.v_splitter)
        self.h_splitter.setStretchFactor(0, 4)
        self.h_splitter.setStretchFactor(1, 6)
        self.h_splitter.setSizes([380, 640])

        main_vbox.addWidget(self.h_splitter, stretch=1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(True)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Add audio files to begin.")

        # Wire Signals
        self.track_list.track_selected.connect(self._on_track_selected)
        self.range_selector.range_changed.connect(self._on_range_changed)
        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.settings_panel.free_ram_requested.connect(self._on_free_ram_clicked)

        # Initial state
        self.range_selector.set_track(None)

    def _check_dependencies(self) -> None:
        ok, msg = check_ffmpeg_installed()
        if not ok:
            QMessageBox.critical(
                self,
                "FFmpeg Missing",
                f"FFmpeg or FFprobe was not detected on your system PATH:\n\n{msg}\n\n"
                f"Whisper GUI requires FFmpeg to slice and decode audio tracks. "
                f"Please install ffmpeg (e.g. 'sudo apt install ffmpeg' on Ubuntu or 'brew install ffmpeg' on macOS).",
            )

    def _on_track_selected(self, track: AudioTrack | None) -> None:
        """User clicked or navigated to a track in the list."""
        self.range_selector.set_track(track)
        if track and track.result and track.result.docx_path:
            self.transcript_view.set_completed_docx(track.result.docx_path)
            if track.result.polished_text:
                self.transcript_view.set_polished_text(
                    track.result.polished_text, track.result.llm_model_used or ""
                )

    def _on_range_changed(self, track_id: str) -> None:
        """Update table display when user modifies start/end slicing."""
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

        # Check if LLM polish is enabled but API key is missing
        llm_cfg = self.llm_panel.get_config()
        if llm_cfg.enabled and not llm_cfg.api_key.strip() and llm_cfg.provider != "Custom":
            QMessageBox.warning(
                self,
                "API Key Required",
                "You have enabled LLM Text Polishing, but no API Key is entered.\n\n"
                "Please enter your API Key in the 'Text Polish' tab, or uncheck the toggle to proceed with pure Whisper transcription.",
            )
            # Switch to LLM tab
            self.config_tabs.setCurrentIndex(2)
            return

        pending_tracks = [t for t in tracks if t.status in (TrackStatus.QUEUED, TrackStatus.ERROR)]
        if not pending_tracks:
            reply = QMessageBox.question(
                self,
                "Re-run Transcription?",
                "All tracks in the queue are already completed. Do you want to transcribe them again?",
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

        # Update UI state
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.track_list.setEnabled(False)
        self.range_selector.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.llm_panel.setEnabled(False)
        self.status_bar.showMessage("Transcription running in background...")

        # Create worker
        self.current_worker = TranscriptionWorker(
            tracks=pending_tracks,
            transcription_config=config,
            transcriber=self.transcriber,
            parent=self,
        )

        # Connect worker signals
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
            self.transcript_view.set_status("Stopping transcription...")
            self.status_bar.showMessage("Stopping transcription process...")
            self.current_worker.request_stop()
            self.btn_stop.setEnabled(False)

    def _on_worker_track_started(self, track_id: str) -> None:
        self.track_list.refresh_track_display(track_id)

    def _on_free_ram_clicked(self) -> None:
        self.transcriber.unload_model()
        self.settings_panel.set_ram_status(False)
        self.status_bar.showMessage("Whisper model unloaded from memory (RAM freed).")

    def _on_worker_status_updated(self, track_id: str, message: str) -> None:
        self.transcript_view.set_status(message)
        self.status_bar.showMessage(message)
        self.track_list.refresh_track_display(track_id)
        if self.transcriber.is_loaded:
            self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)

    def _on_worker_segment_received(self, track_id: str, segment: TranscriptSegment) -> None:
        self.transcript_view.append_segment(segment)

    def _on_worker_progress_updated(self, track_id: str, percent: int, time_str: str) -> None:
        self.transcript_view.set_progress(percent, time_str)

    def _on_worker_track_completed(self, track_id: str, result: TranscriptionResult) -> None:
        self.track_list.refresh_track_display(track_id)
        if result.polished_text:
            self.transcript_view.set_polished_text(
                result.polished_text, result.llm_model_used or ""
            )
        if result.docx_path:
            self.transcript_view.set_completed_docx(result.docx_path)
            self.status_bar.showMessage(f"Completed! Document saved: {result.docx_path.name}")
        if self.transcriber.is_loaded:
            self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)

    def _on_worker_track_error(self, track_id: str, error_msg: str) -> None:
        self.track_list.refresh_track_display(track_id)
        self.transcript_view.set_status(f"Error: {error_msg}")
        self.status_bar.showMessage(f"Error on track: {error_msg}")

    def _on_worker_finished(self) -> None:
        self._reset_ui_state()
        if self.settings_panel.chk_auto_unload.isChecked():
            self.transcriber.unload_model()
            self.settings_panel.set_ram_status(False)
            self.status_bar.showMessage("All tracks processed and model unloaded from RAM.")
        else:
            if self.transcriber.is_loaded:
                self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)
            self.status_bar.showMessage("All tracks processed successfully!")

        QMessageBox.information(
            self,
            "Done",
            "Transcription completed! You can now open your Word (.docx) document.",
        )

    def _on_worker_cancelled(self) -> None:
        self._reset_ui_state()
        self.status_bar.showMessage("Transcription stopped by user.")

    def _reset_ui_state(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.track_list.setEnabled(True)
        self.range_selector.setEnabled(True)
        self.settings_panel.setEnabled(True)
        self.llm_panel.setEnabled(True)
        self.current_worker = None

    def _load_settings(self) -> None:
        settings = QSettings("WhisperGUI", "WhisperAudioTranscriber")
        self.settings_panel.load_settings(settings)
        self.llm_panel.load_settings(settings)

    def _save_settings(self) -> None:
        settings = QSettings("WhisperGUI", "WhisperAudioTranscriber")
        self.settings_panel.save_settings(settings)
        self.llm_panel.save_settings(settings)

    def closeEvent(self, event) -> None:
        """Ensure background threads are safely terminated upon exit and settings saved."""
        self._save_settings()
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.request_stop()
            self.current_worker.wait(3000)
        event.accept()
