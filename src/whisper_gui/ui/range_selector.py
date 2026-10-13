"""Interactive widget for choosing the audio duration and range to transcribe."""

from __future__ import annotations

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.audio_utils import format_seconds
from whisper_gui.models import AudioTrack, SliceConfig, SliceMode


class RangeSelectorWidget(QGroupBox):
    """Allows user to specify whether to transcribe full audio or a sliced segment."""

    range_changed = Signal(float, float)  # start_sec, end_sec

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Audio Length & Slicing (ffmpeg)", parent)
        self._total_duration: float = 0.0
        self._current_track: AudioTrack | None = None
        self._updating_ui: bool = False

        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 14, 12, 12)

        # Mode selection
        mode_layout = QHBoxLayout()
        self.btn_group_mode = QButtonGroup(self)

        self.radio_full = QRadioButton("Full Audio")
        self.radio_custom = QRadioButton("Custom Time Range")
        self.radio_full.setChecked(True)

        self.btn_group_mode.addButton(self.radio_full, 0)
        self.btn_group_mode.addButton(self.radio_custom, 1)

        mode_layout.addWidget(self.radio_full)
        mode_layout.addWidget(self.radio_custom)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Quick preset buttons
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Quick Presets:"))
        self.btn_preset_5m = QPushButton("First 5m")
        self.btn_preset_10m = QPushButton("First 10m")
        self.btn_preset_15m = QPushButton("First 15m")
        self.btn_preset_30m = QPushButton("First 30m")
        self.btn_preset_full = QPushButton("Reset Full")

        for btn in (self.btn_preset_5m, self.btn_preset_10m, self.btn_preset_15m, self.btn_preset_30m, self.btn_preset_full):
            btn.setMaximumHeight(26)
            preset_layout.addWidget(btn)

        preset_layout.addStretch()
        layout.addLayout(preset_layout)

        # Time inputs container
        self.time_container = QFrame()
        self.time_container.setFrameShape(QFrame.StyledPanel)
        time_layout = QHBoxLayout(self.time_container)
        time_layout.setContentsMargins(8, 6, 8, 6)

        time_layout.addWidget(QLabel("Start:"))
        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm:ss")
        self.time_start.setTime(QTime(0, 0, 0))
        time_layout.addWidget(self.time_start)

        time_layout.addSpacing(16)
        time_layout.addWidget(QLabel("End:"))
        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm:ss")
        self.time_end.setTime(QTime(0, 0, 0))
        time_layout.addWidget(self.time_end)

        time_layout.addSpacing(20)
        self.lbl_selected_length = QLabel("Selected Length: 00:00:00")
        self.lbl_selected_length.setStyleSheet("font-weight: bold; color: #1a5276;")
        time_layout.addWidget(self.lbl_selected_length)
        time_layout.addStretch()

        layout.addWidget(self.time_container)

        # Visual progress/range indicator slider
        slider_layout = QVBoxLayout()
        self.slider_range = QSlider(Qt.Horizontal)
        self.slider_range.setRange(0, 1000)
        self.slider_range.setValue(1000)
        self.slider_range.setToolTip("Audio length range preview")
        slider_layout.addWidget(self.slider_range)

        self.lbl_slider_info = QLabel("Position: 00:00:00 / 00:00:00")
        self.lbl_slider_info.setStyleSheet("color: #6c757d; font-size: 11px;")
        slider_layout.addWidget(self.lbl_slider_info)
        layout.addLayout(slider_layout)

        # Connect signals
        self.radio_full.toggled.connect(self._on_mode_toggled)
        self.radio_custom.toggled.connect(self._on_mode_toggled)

        self.time_start.timeChanged.connect(self._on_time_changed)
        self.time_end.timeChanged.connect(self._on_time_changed)

        self.btn_preset_5m.clicked.connect(lambda: self._apply_preset(300))
        self.btn_preset_10m.clicked.connect(lambda: self._apply_preset(600))
        self.btn_preset_15m.clicked.connect(lambda: self._apply_preset(900))
        self.btn_preset_30m.clicked.connect(lambda: self._apply_preset(1800))
        self.btn_preset_full.clicked.connect(self._apply_full_preset)

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

        self.slider_range.setRange(0, max(1, int(self._total_duration)))
        self.slider_range.setValue(int(cfg.effective_end(self._total_duration)))

        self._updating_ui = False
        self._update_readout()
        self._update_container_enabled_state()

    def _update_container_enabled_state(self) -> None:
        custom_enabled = self.radio_custom.isChecked()
        self.time_container.setEnabled(custom_enabled)
        for btn in (self.btn_preset_5m, self.btn_preset_10m, self.btn_preset_15m, self.btn_preset_30m):
            btn.setEnabled(custom_enabled)

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
            # Custom range
            s = self._qtime_to_seconds(self.time_start.time())
            e = self._qtime_to_seconds(self.time_end.time())
            self._notify_change(s, e, SliceMode.RANGE)
        self._update_readout()

    def _apply_preset(self, duration_sec: float) -> None:
        self.radio_custom.setChecked(True)
        self._updating_ui = True
        self._set_qtime(self.time_start, 0.0)
        end = min(self._total_duration, duration_sec)
        self._set_qtime(self.time_end, end)
        self.slider_range.setValue(int(end))
        self._updating_ui = False
        self._notify_change(0.0, end, SliceMode.RANGE)
        self._update_readout()

    def _apply_full_preset(self) -> None:
        self.radio_full.setChecked(True)
        self._on_mode_toggled()

    def _on_time_changed(self) -> None:
        if self._updating_ui or not self.radio_custom.isChecked():
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
            self.lbl_selected_length.setText("Selected Length: 00:00:00")
            self.lbl_slider_info.setText("Position: 00:00:00 / 00:00:00")
            return

        if self.radio_full.isChecked():
            dur_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(f"Selected Length: {dur_str} (Full Audio)")
            self.lbl_slider_info.setText(f"Range: 00:00:00 → {dur_str} / Total: {dur_str}")
        else:
            start_sec = self._qtime_to_seconds(self.time_start.time())
            end_sec = self._qtime_to_seconds(self.time_end.time())
            dur = max(0.0, end_sec - start_sec)
            s_str = format_seconds(start_sec)
            e_str = format_seconds(end_sec)
            d_str = format_seconds(dur)
            t_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(f"Selected Length: {d_str}")
            self.lbl_slider_info.setText(f"Range: {s_str} → {e_str} (Duration: {d_str}) / Total: {t_str}")

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
