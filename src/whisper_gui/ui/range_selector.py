"""Interactive widget for choosing audio duration and range to transcribe."""

from __future__ import annotations

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
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

from whisper_gui.audio_utils import format_seconds
from whisper_gui.models import AudioTrack, SliceConfig, SliceMode


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
        layout.setSpacing(6)
        layout.setContentsMargins(10, 8, 10, 8)

        # Top row: Mode Selection + Presets in a compact horizontal layout
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.btn_group_mode = QButtonGroup(self)
        self.radio_full = QRadioButton("Full Audio")
        self.radio_custom = QRadioButton("Custom Range")
        self.radio_full.setChecked(True)

        self.btn_group_mode.addButton(self.radio_full, 0)
        self.btn_group_mode.addButton(self.radio_custom, 1)

        top_row.addWidget(self.radio_full)
        top_row.addWidget(self.radio_custom)
        top_row.addSpacing(12)

        # Quick preset buttons
        preset_lbl = QLabel("Presets:")
        preset_lbl.setStyleSheet("color: #6c757d; font-size: 11px;")
        top_row.addWidget(preset_lbl)

        self.btn_preset_5m = QPushButton("5m")
        self.btn_preset_10m = QPushButton("10m")
        self.btn_preset_15m = QPushButton("15m")
        self.btn_preset_30m = QPushButton("30m")
        self.btn_preset_full = QPushButton("Full")

        btn_style = """
            QPushButton {
                padding: 2px 7px;
                font-size: 11px;
                border: 1px solid #ced4da;
                border-radius: 3px;
                background-color: #f8f9fa;
            }
            QPushButton:hover {
                background-color: #e9ecef;
            }
        """

        for btn in (self.btn_preset_5m, self.btn_preset_10m, self.btn_preset_15m, self.btn_preset_30m, self.btn_preset_full):
            btn.setStyleSheet(btn_style)
            btn.setMaximumHeight(22)
            top_row.addWidget(btn)

        top_row.addStretch()
        layout.addLayout(top_row)

        # Middle row: Time inputs container
        self.time_container = QFrame()
        self.time_container.setFrameShape(QFrame.StyledPanel)
        self.time_container.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 4px;
            }
        """)
        time_layout = QHBoxLayout(self.time_container)
        time_layout.setContentsMargins(8, 4, 8, 4)
        time_layout.setSpacing(8)

        lbl_start = QLabel("Start:")
        lbl_start.setStyleSheet("font-weight: bold; font-size: 11px;")
        time_layout.addWidget(lbl_start)

        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm:ss")
        self.time_start.setTime(QTime(0, 0, 0))
        self.time_start.setMaximumWidth(85)
        time_layout.addWidget(self.time_start)

        time_layout.addSpacing(8)
        lbl_end = QLabel("End:")
        lbl_end.setStyleSheet("font-weight: bold; font-size: 11px;")
        time_layout.addWidget(lbl_end)

        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm:ss")
        self.time_end.setTime(QTime(0, 0, 0))
        self.time_end.setMaximumWidth(85)
        time_layout.addWidget(self.time_end)

        time_layout.addSpacing(12)
        self.lbl_selected_length = QLabel("Selected Length: 00:00:00")
        self.lbl_selected_length.setStyleSheet("font-weight: bold; color: #1a5276; font-size: 11px;")
        time_layout.addWidget(self.lbl_selected_length)
        time_layout.addStretch()

        layout.addWidget(self.time_container)

        # Bottom row: Slider + position info
        slider_layout = QVBoxLayout()
        slider_layout.setSpacing(2)

        self.slider_range = QSlider(Qt.Horizontal)
        self.slider_range.setRange(0, 1000)
        self.slider_range.setValue(1000)
        self.slider_range.setToolTip("Drag to adjust ending point of transcription")
        slider_layout.addWidget(self.slider_range)

        self.lbl_slider_info = QLabel("Position: 00:00:00 / 00:00:00")
        self.lbl_slider_info.setStyleSheet("color: #6c757d; font-size: 10px;")
        slider_layout.addWidget(self.lbl_slider_info)

        layout.addLayout(slider_layout)

        # Wire Signals
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
