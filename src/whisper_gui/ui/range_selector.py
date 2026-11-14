"""Interactive widget for choosing audio duration and range to transcribe."""

from __future__ import annotations

from PySide6.QtCore import QSize, QTime, QUrl, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]

from whisper_gui.audio_utils import format_seconds
from whisper_gui.models import AudioTrack, SliceConfig, SliceMode
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_SURFACE,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    fixed_mono_font,
    load_ui_icon,
)


class RangeSelectorWidget(QWidget):
    """Allows user to specify whether to transcribe full audio or a sliced segment."""

    range_changed = Signal(float, float)  # start_sec, end_sec

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._total_duration: float = 0.0
        self._current_track: AudioTrack | None = None
        self._updating_ui: bool = False

        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Two-row control card: Mode + duration on row 1, Start/End timecodes on row 2
        top_bar = QFrame()
        top_bar.setObjectName("range_top_bar")
        top_bar.setStyleSheet(f"""
            #range_top_bar {{
                background-color: {COLOR_BG_INPUT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        top_vbox = QVBoxLayout(top_bar)
        top_vbox.setContentsMargins(12, 12, 12, 12)
        top_vbox.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)

        self.btn_group_mode = QButtonGroup(self)
        self.radio_full = QRadioButton("Full Audio")
        self.radio_custom = QRadioButton("Custom Range")
        self.radio_full.setChecked(True)

        self.btn_group_mode.addButton(self.radio_full, 0)
        self.btn_group_mode.addButton(self.radio_custom, 1)

        mode_row.addWidget(self.radio_full)
        mode_row.addWidget(self.radio_custom)
        mode_row.addStretch()

        self.lbl_selected_length = QLabel("Selected: 00:00:00")
        self.lbl_selected_length.setFont(fixed_mono_font(12))
        self.lbl_selected_length.setStyleSheet(f"color: {COLOR_TEXT_MAIN};")
        mode_row.addWidget(self.lbl_selected_length)
        top_vbox.addLayout(mode_row)

        time_row = QHBoxLayout()
        time_row.setSpacing(12)

        lbl_start = QLabel("Start")
        lbl_start.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        time_row.addWidget(lbl_start)

        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm:ss")
        self.time_start.setTime(QTime(0, 0, 0))
        self.time_start.setMinimumWidth(116)
        self.time_start.setFont(fixed_mono_font(12))
        time_row.addWidget(self.time_start)

        time_row.addSpacing(4)

        lbl_end = QLabel("End")
        lbl_end.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        time_row.addWidget(lbl_end)

        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm:ss")
        self.time_end.setTime(QTime(0, 0, 0))
        self.time_end.setMinimumWidth(116)
        self.time_end.setFont(fixed_mono_font(12))
        time_row.addWidget(self.time_end)

        time_row.addStretch()
        top_vbox.addLayout(time_row)

        layout.addWidget(top_bar)

        # Slider + position info
        slider_layout = QVBoxLayout()
        slider_layout.setSpacing(4)

        self.slider_range = QSlider(Qt.Horizontal)
        self.slider_range.setRange(0, 1000)
        self.slider_range.setValue(1000)
        slider_layout.addWidget(self.slider_range)

        self.lbl_slider_info = QLabel("Range: 00:00:00 / Total: 00:00:00")
        self.lbl_slider_info.setFont(fixed_mono_font(11))
        self.lbl_slider_info.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        slider_layout.addWidget(self.lbl_slider_info)

        layout.addLayout(slider_layout)

        # Wire Signals
        self.radio_full.toggled.connect(self._on_mode_toggled)
        self.radio_custom.toggled.connect(self._on_mode_toggled)
        self.time_start.timeChanged.connect(self._on_time_changed)
        self.time_end.timeChanged.connect(self._on_time_changed)
        self.slider_range.valueChanged.connect(self._on_slider_changed)

        self._update_container_enabled_state()

    def set_track(self, track: AudioTrack | None) -> None:
        """Set the active track being inspected and configured."""
        self._current_track = track
        if track is None:
            self._total_duration = 0.0
            self.setEnabled(False)
            self.lbl_selected_length.setText("No track selected")
            self.lbl_slider_info.setText("Position: 00:00:00 / 00:00:00")
            return

        self.setEnabled(True)
        self._total_duration = track.info.duration
        self._updating_ui = True

        cfg = track.slice_config
        if cfg.mode == SliceMode.FULL or cfg.is_full(self._total_duration):
            self.radio_full.setChecked(True)
            self._set_qtime(self.time_start, 0.0)
            self._set_qtime(self.time_end, self._total_duration)
        else:
            self.radio_custom.setChecked(True)
            self._set_qtime(self.time_start, cfg.start_sec)
            self._set_qtime(self.time_end, cfg.effective_end(self._total_duration))

        total_int = int(round(self._total_duration))
        self.slider_range.setRange(0, max(1, total_int))
        eff_end = cfg.effective_end(self._total_duration)
        self.slider_range.setValue(int(eff_end))
        self._updating_ui = False

        self._update_container_enabled_state()
        self._update_readout()

    def _on_mode_toggled(self) -> None:
        if self._updating_ui:
            return
        self._update_container_enabled_state()
        if self.radio_full.isChecked():
            self._updating_ui = True
            self._set_qtime(self.time_start, 0.0)
            self._set_qtime(self.time_end, self._total_duration)
            self.slider_range.setValue(int(self._total_duration))
            self._updating_ui = False
            self._notify_change(0.0, self._total_duration, SliceMode.FULL)
        else:
            start_sec = self._qtime_to_seconds(self.time_start.time())
            end_sec = self._qtime_to_seconds(self.time_end.time())
            self._notify_change(start_sec, end_sec, SliceMode.RANGE)
        self._update_readout()

    def _update_container_enabled_state(self) -> None:
        custom_enabled = self.radio_custom.isChecked()
        self.time_start.setEnabled(custom_enabled)
        self.time_end.setEnabled(custom_enabled)
        self.slider_range.setEnabled(custom_enabled)

    def _on_time_changed(self) -> None:
        if self._updating_ui:
            return
        start_sec = self._qtime_to_seconds(self.time_start.time())
        end_sec = self._qtime_to_seconds(self.time_end.time())

        # Clamp start to total
        if start_sec > self._total_duration:
            start_sec = self._total_duration
            self._set_qtime(self.time_start, start_sec)

        # Clamp end to total
        if end_sec > self._total_duration:
            end_sec = self._total_duration
            self._set_qtime(self.time_end, end_sec)

        # Ensure end >= start
        if end_sec < start_sec:
            end_sec = start_sec
            self._set_qtime(self.time_end, end_sec)

        self._updating_ui = True
        self.slider_range.setValue(int(end_sec))
        self._updating_ui = False

        self._notify_change(start_sec, end_sec, SliceMode.RANGE)
        self._update_readout()

    def _on_slider_changed(self, value: int) -> None:
        if self._updating_ui:
            return
        if self.radio_custom.isChecked():
            start_sec = self._qtime_to_seconds(self.time_start.time())
            new_end = max(start_sec, float(value))
            self._updating_ui = True
            self._set_qtime(self.time_end, new_end)
            self._updating_ui = False
            self._notify_change(start_sec, new_end, SliceMode.RANGE)
            self._update_readout()

    def _notify_change(self, start_sec: float, end_sec: float, mode: SliceMode) -> None:
        if self._current_track is not None:
            self._current_track.slice_config = SliceConfig(
                mode=mode,
                start_sec=start_sec,
                end_sec=end_sec,
            )
        self.range_changed.emit(start_sec, end_sec)

    def _update_readout(self) -> None:
        if self._total_duration <= 0:
            self.lbl_selected_length.setText("Selected: 00:00:00")
            self.lbl_slider_info.setText("Position: 00:00:00 / 00:00:00")
            return

        if self.radio_full.isChecked():
            dur_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(f"Selected: {dur_str} (Full Audio)")
            self.lbl_slider_info.setText(f"Range: 00:00:00 → {dur_str} / Total: {dur_str}")
        else:
            start_sec = self._qtime_to_seconds(self.time_start.time())
            end_sec = self._qtime_to_seconds(self.time_end.time())
            dur = max(0.0, end_sec - start_sec)
            s_str = format_seconds(start_sec)
            e_str = format_seconds(end_sec)
            d_str = format_seconds(dur)
            t_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(f"Selected: {d_str}")
            self.lbl_slider_info.setText(f"Range: {s_str} → {e_str} ({d_str}) / Total: {t_str}")

    @staticmethod
    def _set_qtime(time_widget: QTimeEdit, seconds: float) -> None:
        total = int(max(0.0, seconds))
        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60
        time_widget.setTime(QTime(h, m, s))

    @staticmethod
    def _qtime_to_seconds(t: QTime) -> float:
        return float(t.hour() * 3600 + t.minute() * 60 + t.second())


class TrimAudioDialog(QDialog):
    """Clean on-demand modal dialog for audio range selection."""

    def __init__(self, track: AudioTrack, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.track = track
        self._player = None
        self._audio_output = None
        self._preview_end_ms: int | None = None
        self._duration_ms: int = int(round(max(0.0, track.info.duration) * 1000))

        self.setWindowTitle(f"Trim Audio - {track.info.filename}")
        self.setMinimumWidth(520)
        self.resize(560, 300)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel(f"Trim {track.info.filename}")
        title.setStyleSheet(f"font-weight: 500; font-size: 14px; color: {COLOR_TEXT_MAIN};")
        layout.addWidget(title)

        self.selector = RangeSelectorWidget(self)
        self.selector.set_track(track)
        layout.addWidget(self.selector)

        # Compact audio preview bar
        preview_bar = QFrame()
        preview_bar.setObjectName("trim_preview_bar")
        preview_bar.setStyleSheet(f"""
            #trim_preview_bar {{
                background-color: {COLOR_BG_INPUT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        preview_layout = QHBoxLayout(preview_bar)
        preview_layout.setContentsMargins(12, 8, 12, 8)
        preview_layout.setSpacing(8)

        self.btn_play_pause = QPushButton("Play")
        self.btn_play_pause.setIcon(load_ui_icon("play"))
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.clicked.connect(self._on_play_pause)
        preview_layout.addWidget(self.btn_play_pause)

        self.btn_play_selection = QPushButton("Preview Range")
        self.btn_play_selection.setIcon(load_ui_icon("play"))
        self.btn_play_selection.setIconSize(QSize(14, 14))
        self.btn_play_selection.clicked.connect(self._on_play_selection)
        preview_layout.addWidget(self.btn_play_selection)

        preview_layout.addStretch()

        self.lbl_playback_pos = QLabel("00:00:00 / 00:00:00")
        self.lbl_playback_pos.setFont(fixed_mono_font(11))
        self.lbl_playback_pos.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        preview_layout.addWidget(self.lbl_playback_pos)

        layout.addWidget(preview_bar)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Ok).setText("Apply")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.selector.range_changed.connect(self._on_range_changed)
        self._init_player()

    def _init_player(self) -> None:
        has_media = False
        if QMediaPlayer is not None and QAudioOutput is not None and self.track.file_path.is_file():
            try:
                player = QMediaPlayer(self)
                audio_output = QAudioOutput(self)
                player.setAudioOutput(audio_output)
                player.positionChanged.connect(self._on_position_changed)
                player.durationChanged.connect(self._on_duration_changed)
                player.playbackStateChanged.connect(self._on_playback_state_changed)
                player.setSource(QUrl.fromLocalFile(str(self.track.file_path)))
                self._player = player
                self._audio_output = audio_output
                has_media = True
            except Exception:
                self._player = None
                self._audio_output = None

        self.btn_play_pause.setEnabled(has_media)
        self.btn_play_selection.setEnabled(has_media)

    def _on_play_pause(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._preview_end_ms = None
            self._player.play()

    def _on_play_selection(self) -> None:
        if self._player is None:
            return
        cfg = self.track.slice_config
        total = self.track.info.duration
        if cfg.mode == SliceMode.FULL:
            start_sec = 0.0
            end_sec = total
        else:
            start_sec = max(0.0, cfg.start_sec)
            end_sec = cfg.effective_end(total)

        start_ms = int(round(start_sec * 1000))
        end_ms = int(round(end_sec * 1000))
        if end_ms <= start_ms:
            self._preview_end_ms = None
            self._player.setPosition(start_ms)
            self._player.pause()
            return

        self._preview_end_ms = end_ms
        self._player.setPosition(start_ms)
        self._player.play()

    def _on_range_changed(self, _start_sec: float, end_sec: float) -> None:
        if self._preview_end_ms is not None:
            self._preview_end_ms = int(round(end_sec * 1000))

    def _on_duration_changed(self, duration_ms: int) -> None:
        if duration_ms > 0:
            self._duration_ms = duration_ms
        pos_ms = self._player.position() if self._player is not None else 0
        self._update_position_label(pos_ms)

    def _on_position_changed(self, position_ms: int) -> None:
        self._update_position_label(position_ms)
        if self._preview_end_ms is not None and position_ms >= self._preview_end_ms:
            self._preview_end_ms = None
            if (
                self._player is not None
                and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            ):
                self._player.pause()

    def _on_playback_state_changed(self, state: object) -> None:
        if QMediaPlayer is not None and state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play_pause.setText("Pause")
            self.btn_play_pause.setIcon(load_ui_icon("pause"))
        else:
            self.btn_play_pause.setText("Play")
            self.btn_play_pause.setIcon(load_ui_icon("play"))
            if QMediaPlayer is not None and state == QMediaPlayer.PlaybackState.StoppedState:
                self._preview_end_ms = None

    def _update_position_label(self, position_ms: int) -> None:
        total_ms = self._duration_ms
        if self._player is not None and self._player.duration() > 0:
            total_ms = self._player.duration()
        self.lbl_playback_pos.setText(
            f"{self._format_hhmmss(position_ms)} / {self._format_hhmmss(total_ms)}"
        )

    @staticmethod
    def _format_hhmmss(ms: int) -> str:
        total_secs = max(0, int(ms // 1000))
        hours = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        return f"{hours:02d}:{mins:02d}:{secs:02d}"

    def _release_player(self) -> None:
        self._preview_end_ms = None
        if self._player is not None:
            try:
                self._player.blockSignals(True)
                self._player.stop()
                self._player.setSource(QUrl())
                self._player.setAudioOutput(None)
            except Exception:
                pass
            self._player.deleteLater()
            self._player = None
        if self._audio_output is not None:
            self._audio_output.blockSignals(True)
            self._audio_output.deleteLater()
            self._audio_output = None

    def accept(self) -> None:
        self._release_player()
        super().accept()

    def reject(self) -> None:
        self._release_player()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._release_player()
        super().closeEvent(event)

