"""Main window for Whisper GUI desktop application with responsive non-fullscreen layouts."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
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
from whisper_gui.ui.range_selector import RangeSelectorWidget
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.track_list_widget import TrackListWidget
from whisper_gui.ui.transcript_view import TranscriptView
from whisper_gui.worker import TranscriptionWorker


class MainWindow(QMainWindow):
    """Main application window for Whisper GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Whisper GUI - Audio Transcription & Docx Export v{__version__}")
        self.resize(1100, 720)
        self.setMinimumSize(780, 500)

        # Transcriber singleton for caching models
        self.transcriber = Transcriber()
        self.current_worker: TranscriptionWorker | None = None

        self._build_ui()
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
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 5px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(10)

        title_lbl = QLabel("🎙️ Whisper Audio Transcriber")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet("color: #1a5276;")
        header_layout.addWidget(title_lbl)

        header_layout.addStretch()

        # Primary Action Buttons
        self.btn_start = QPushButton("▶ Start Transcription")
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 6px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #7f8c8d;
            }
        """)
        header_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
                font-size: 12px;
                padding: 6px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #e74c3c;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #7f8c8d;
            }
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
        self.config_tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background: #e9ecef;
                color: #495057;
                padding: 5px 14px;
                font-weight: bold;
                font-size: 11px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #1a5276;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background: #dee2e6;
            }
        """)

        # Tab 1: Range Selector in scroll area (prevents clipping when window is shrunk)
        self.range_selector = RangeSelectorWidget()
        scroll_range = QScrollArea()
        scroll_range.setWidgetResizable(True)
        scroll_range.setFrameShape(QFrame.NoFrame)
        scroll_range.setWidget(self.range_selector)
        self.config_tabs.addTab(scroll_range, "✂️ Audio Trimming (ffmpeg)")

        # Tab 2: Settings Panel in scroll area
        self.settings_panel = SettingsPanel()
        scroll_settings = QScrollArea()
        scroll_settings.setWidgetResizable(True)
        scroll_settings.setFrameShape(QFrame.NoFrame)
        scroll_settings.setWidget(self.settings_panel)
        self.config_tabs.addTab(scroll_settings, "⚙️ Model & Output Settings")

        self.v_splitter.addWidget(self.config_tabs)

        # Bottom of right pane: Live Transcript & Export view
        self.transcript_view = TranscriptView()
        self.v_splitter.addWidget(self.transcript_view)

        # Proportion settings: config tabs compact, transcript view gets majority of room
        self.v_splitter.setStretchFactor(0, 0)
        self.v_splitter.setStretchFactor(1, 1)
        self.v_splitter.setSizes([160, 440])

        self.h_splitter.addWidget(self.v_splitter)
        self.h_splitter.setStretchFactor(0, 4)
        self.h_splitter.setStretchFactor(1, 6)
        self.h_splitter.setSizes([380, 620])

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

        # Initial state
        self.range_selector.set_track(None)

    def _check_dependencies(self) -> None:
        ok, msg = check_ffmpeg_installed()
        if not ok:
            QMessageBox.critical(
                self,
                "FFmpeg Error",
                f"FFmpeg or FFprobe could not be found or executed:\n\n{msg}\n\nPlease install ffmpeg on your system or place the binary in the application folder.",
            )
            self.status_bar.showMessage(f"Error: {msg}")
        else:
            self.status_bar.showMessage(f"Ready. {msg.split(',')[0]}")

    def _on_track_selected(self, track: AudioTrack | None) -> None:
        self.range_selector.set_track(track)
        if track:
            # Switch to trimming tab for immediate track editing
            self.config_tabs.setCurrentIndex(0)
            if track.result and track.result.docx_path:
                self.transcript_view.set_completed_docx(track.result.docx_path)
                self.transcript_view.set_status(f"Completed ({track.result.speed_factor:.1f}x speed)")
                self.transcript_view.set_progress(100)

    def _on_range_changed(self, start_sec: float, end_sec: float) -> None:
        track = self.track_list.get_selected_track()
        if track:
            self.track_list.refresh_track_display(track.id)

    def _on_start_clicked(self) -> None:
        tracks = self.track_list.get_tracks()
        if not tracks:
            QMessageBox.information(
                self,
                "No Audio Files",
                "Please add at least one audio file to transcribe.",
            )
            return

        # Check pending tracks
        pending_tracks = [t for t in tracks if t.status != TrackStatus.COMPLETED]
        if not pending_tracks:
            reply = QMessageBox.question(
                self,
                "Re-transcribe?",
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
        self.transcript_view.clear_view()

        # Update UI state
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.track_list.setEnabled(False)
        self.range_selector.setEnabled(False)
        self.settings_panel.setEnabled(False)
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

    def _on_worker_status_updated(self, track_id: str, message: str) -> None:
        self.transcript_view.set_status(message)
        self.status_bar.showMessage(message)
        self.track_list.refresh_track_display(track_id)

    def _on_worker_segment_received(self, track_id: str, segment: TranscriptSegment) -> None:
        self.transcript_view.append_segment(segment)

    def _on_worker_progress_updated(self, track_id: str, percent: int, time_str: str) -> None:
        self.transcript_view.set_progress(percent, time_str)

    def _on_worker_track_completed(self, track_id: str, result: TranscriptionResult) -> None:
        self.track_list.refresh_track_display(track_id)
        if result.docx_path:
            self.transcript_view.set_completed_docx(result.docx_path)
            self.status_bar.showMessage(f"Completed! Document saved: {result.docx_path.name}")

    def _on_worker_track_error(self, track_id: str, error_msg: str) -> None:
        self.track_list.refresh_track_display(track_id)
        self.transcript_view.set_status(f"Error: {error_msg}")
        self.status_bar.showMessage(f"Error on track: {error_msg}")

    def _on_worker_finished(self) -> None:
        self._reset_ui_state()
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
        self.current_worker = None

    def closeEvent(self, event) -> None:
        """Ensure background threads are safely terminated upon exit."""
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.request_stop()
            self.current_worker.wait(3000)
        event.accept()
