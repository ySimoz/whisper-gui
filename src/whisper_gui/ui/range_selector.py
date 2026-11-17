"""Interactive widget for choosing audio duration and range to transcribe."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, QThread, QTime, QUrl, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor, QMouseEvent, QPainter, QPen, QPolygonF, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]

from whisper_gui.audio_utils import extract_waveform_peaks, format_seconds
from whisper_gui.i18n import tr
from whisper_gui.models import AudioTrack, SliceConfig, SliceMode
from whisper_gui.ui.theme import fixed_mono_font, get_palette, load_ui_icon

_WAVEFORM_CACHE: dict[tuple[str, int, int, int], list[float]] = {}
_WAVEFORM_CACHE_MAX = 32
_DEFAULT_WAVEFORM_BINS = 160


def _cache_key(path: Path, num_bins: int) -> tuple[str, int, int, int] | None:
    try:
        st = path.stat()
        return (str(path.resolve()), st.st_mtime_ns, st.st_size, num_bins)
    except OSError:
        return None


class WaveformLoadWorker(QThread):
    """Background worker that extracts downsampled waveform peaks without blocking UI."""

    peaks_ready = Signal(int, list)  # request_id, list[float]

    def __init__(
        self,
        file_path: Path,
        num_bins: int,
        request_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_path = file_path
        self._num_bins = num_bins
        self._request_id = request_id

    def run(self) -> None:
        peaks = extract_waveform_peaks(
            self._file_path,
            num_bins=self._num_bins,
            should_cancel=self.isInterruptionRequested,
        )
        if not self.isInterruptionRequested():
            self.peaks_ready.emit(self._request_id, peaks)


class WaveformScrubberWidget(QWidget):
    """QPainter-rendered audio waveform with draggable trim handles and click-to-seek playhead."""

    range_dragged = Signal(float, float)  # start_sec, end_sec
    seek_requested = Signal(float)        # position_sec

    _PAD_X = 12.0
    _PAD_Y = 10.0
    _HANDLE_HIT_PX = 10.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peaks: list[float] = []
        self._duration: float = 0.0
        self._start_sec: float = 0.0
        self._end_sec: float = 0.0
        self._playhead_sec: float = -1.0
        self._loading: bool = False
        self._drag_mode: str | None = None  # "start", "end", or "seek"

        self.setFixedHeight(80)
        self.setMouseTracking(True)
        self.setToolTip(tr("range.waveform_tooltip"))

    def retranslate_ui(self) -> None:
        """Update tooltip text for active language."""
        self.setToolTip(tr("range.waveform_tooltip"))
        self.update()

    def clear(self) -> None:
        """Reset waveform state when no track is loaded."""
        self._peaks = []
        self._duration = 0.0
        self._start_sec = 0.0
        self._end_sec = 0.0
        self._playhead_sec = -1.0
        self._loading = False
        self._drag_mode = None
        self.update()

    def set_loading(self, loading: bool) -> None:
        """Display loading indicator state while peaks decode in background."""
        self._loading = loading
        if loading:
            self._peaks = []
        self.update()

    def set_peaks(self, peaks: list[float]) -> None:
        """Set normalized peak amplitudes in [0.0, 1.0]."""
        self._loading = False
        self._peaks = [max(0.0, min(1.0, float(v))) for v in peaks]
        self.update()

    def set_range(self, start_sec: float, end_sec: float, total_duration: float) -> None:
        """Update total duration and active [start_sec, end_sec] selection bounds."""
        self._duration = max(0.0, float(total_duration))
        self._start_sec = max(0.0, min(float(start_sec), self._duration))
        self._end_sec = max(self._start_sec, min(float(end_sec), self._duration))
        self.update()

    def set_playhead(self, seconds: float) -> None:
        """Update playhead position in seconds (-1 hides playhead)."""
        if self._duration <= 0.0:
            self._playhead_sec = -1.0
        else:
            self._playhead_sec = max(0.0, min(float(seconds), self._duration))
        self.update()

    def _inner_rect(self) -> QRectF:
        return QRectF(
            self._PAD_X,
            self._PAD_Y,
            max(1.0, float(self.width()) - 2.0 * self._PAD_X),
            max(1.0, float(self.height()) - 2.0 * self._PAD_Y),
        )

    def _sec_to_x(self, sec: float, rect: QRectF) -> float:
        if self._duration <= 0.0:
            return rect.left()
        ratio = max(0.0, min(1.0, sec / self._duration))
        return rect.left() + ratio * rect.width()

    def _x_to_sec(self, x: float, rect: QRectF) -> float:
        if self._duration <= 0.0 or rect.width() <= 0.0:
            return 0.0
        ratio = max(0.0, min(1.0, (x - rect.left()) / rect.width()))
        return ratio * self._duration

    def _hit_handle(self, x: float, rect: QRectF) -> str | None:
        if self._duration <= 0.0:
            return None
        sx = self._sec_to_x(self._start_sec, rect)
        ex = self._sec_to_x(self._end_sec, rect)
        ds = abs(x - sx)
        de = abs(x - ex)
        if ds <= self._HANDLE_HIT_PX and de <= self._HANDLE_HIT_PX:
            # Disambiguate when handles coincide (e.g. both at 0 or short clip)
            return "end" if x >= ex else "start"
        if ds <= self._HANDLE_HIT_PX:
            return "start"
        if de <= self._HANDLE_HIT_PX:
            return "end"
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled() or self._duration <= 0.0 or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        rect = self._inner_rect()
        x = float(event.position().x())
        handle = self._hit_handle(x, rect)
        if handle is not None:
            self._drag_mode = handle
            self._apply_drag_x(x, rect)
        else:
            self._drag_mode = "seek"
            sec = self._x_to_sec(x, rect)
            self._playhead_sec = sec
            self.update()
            self.seek_requested.emit(sec)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.isEnabled() or self._duration <= 0.0:
            self.unsetCursor()
            super().mouseMoveEvent(event)
            return

        rect = self._inner_rect()
        x = float(event.position().x())

        if self._drag_mode is not None:
            self._apply_drag_x(x, rect)
            event.accept()
            return

        if self._hit_handle(x, rect) is not None:
            self.setCursor(Qt.SizeHorCursor)
        else:
            self.setCursor(Qt.PointingHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_mode is not None and event.button() == Qt.LeftButton:
            self._drag_mode = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _apply_drag_x(self, x: float, rect: QRectF) -> None:
        sec = self._x_to_sec(x, rect)
        if self._drag_mode == "start":
            self._start_sec = max(0.0, min(sec, self._end_sec))
            self.update()
            self.range_dragged.emit(self._start_sec, self._end_sec)
        elif self._drag_mode == "end":
            self._end_sec = max(self._start_sec, min(sec, self._duration))
            self.update()
            self.range_dragged.emit(self._start_sec, self._end_sec)
        elif self._drag_mode == "seek":
            self._playhead_sec = sec
            self.update()
            self.seek_requested.emit(sec)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Card surface + hairline border
        frame_rect = QRectF(0.5, 0.5, max(1.0, self.width() - 1.0), max(1.0, self.height() - 1.0))
        painter.setBrush(QColor(p.bg_input))
        painter.setPen(QPen(QColor(p.border), 1.0))
        painter.drawRoundedRect(frame_rect, 8.0, 8.0)

        rect = self._inner_rect()
        center_y = rect.center().y()

        if self._duration <= 0.0:
            painter.setPen(QPen(QColor(p.border), 1.0))
            painter.drawLine(QPointF(rect.left(), center_y), QPointF(rect.right(), center_y))
            painter.end()
            return

        start_x = self._sec_to_x(self._start_sec, rect)
        end_x = self._sec_to_x(self._end_sec, rect)
        playhead_x = self._sec_to_x(self._playhead_sec, rect) if self._playhead_sec >= 0.0 else -1.0

        # Subtle tint behind active selected range
        sel_w = max(0.0, end_x - start_x)
        if sel_w > 0.5:
            tint = QColor(p.primary)
            tint.setAlpha(24)
            painter.fillRect(QRectF(start_x, rect.top() - 2.0, sel_w, rect.height() + 4.0), tint)

        # Waveform bars or quiet baseline message
        if self._peaks:
            n = len(self._peaks)
            step = rect.width() / float(n)
            bar_w = max(1.5, min(3.0, step * 0.6))
            max_half_h = max(2.0, (rect.height() - 4.0) * 0.5)

            dim_color = QColor(p.border_light)
            dim_color.setAlpha(150)
            active_color = QColor(p.text_secondary if self.isEnabled() else p.text_muted)
            played_color = QColor(p.primary)

            painter.setPen(Qt.NoPen)
            for i, peak in enumerate(self._peaks):
                bx_center = rect.left() + (i + 0.5) * step
                half_h = max(1.5, peak * max_half_h)
                bar_rect = QRectF(bx_center - bar_w * 0.5, center_y - half_h, bar_w, half_h * 2.0)

                in_range = (start_x - 0.5) <= bx_center <= (end_x + 0.5)
                if not in_range:
                    painter.setBrush(dim_color)
                elif playhead_x >= 0.0 and bx_center <= playhead_x:
                    painter.setBrush(played_color)
                else:
                    painter.setBrush(active_color)
                painter.drawRoundedRect(bar_rect, 1.0, 1.0)
        else:
            painter.setPen(QPen(QColor(p.border_light), 1.0))
            painter.drawLine(QPointF(rect.left(), center_y), QPointF(rect.right(), center_y))
            msg = tr("range.waveform_loading") if self._loading else tr("range.waveform_unavailable")
            painter.setPen(QColor(p.text_muted))
            font = painter.font()
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, msg)

        # Crisp [ ] trim boundary brackets
        handle_color = QColor(p.primary if self.isEnabled() else p.text_muted)
        painter.setPen(QPen(handle_color, 2.0))
        top_y = rect.top() - 2.0
        bot_y = rect.bottom() + 2.0
        serif = 5.0

        # Start bracket [
        painter.drawLine(QPointF(start_x, top_y), QPointF(start_x, bot_y))
        painter.drawLine(QPointF(start_x, top_y), QPointF(start_x + serif, top_y))
        painter.drawLine(QPointF(start_x, bot_y), QPointF(start_x + serif, bot_y))

        # End bracket ]
        painter.drawLine(QPointF(end_x, top_y), QPointF(end_x, bot_y))
        painter.drawLine(QPointF(end_x - serif, top_y), QPointF(end_x, top_y))
        painter.drawLine(QPointF(end_x - serif, bot_y), QPointF(end_x, bot_y))

        # Playhead needle
        if playhead_x >= 0.0:
            needle_color = QColor(p.text_main)
            painter.setPen(QPen(needle_color, 1.5))
            painter.drawLine(QPointF(playhead_x, top_y), QPointF(playhead_x, bot_y))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(p.primary))
            tri = QPolygonF(
                [
                    QPointF(playhead_x - 4.0, top_y - 2.0),
                    QPointF(playhead_x + 4.0, top_y - 2.0),
                    QPointF(playhead_x, top_y + 3.0),
                ]
            )
            painter.drawPolygon(tri)

        painter.end()


class RangeSelectorWidget(QWidget):
    """Allows user to specify whether to transcribe full audio or a sliced segment."""

    range_changed = Signal(float, float)  # start_sec, end_sec

    def __init__(self, parent: QWidget | None = None, enable_waveform: bool = True) -> None:
        super().__init__(parent)
        self._total_duration: float = 0.0
        self._current_track: AudioTrack | None = None
        self._updating_ui: bool = False
        self._enable_waveform: bool = enable_waveform
        self._waveform_request_id: int = 0
        self._waveform_workers: list[WaveformLoadWorker] = []

        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Three-row control card: Mode radios on row 1, Start/End on row 2, readout on row 3
        self.top_bar = QFrame()
        self.top_bar.setObjectName("range_top_bar")
        top_vbox = QVBoxLayout(self.top_bar)
        top_vbox.setContentsMargins(12, 12, 12, 12)
        top_vbox.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)

        self.btn_group_mode = QButtonGroup(self)
        self.radio_full = QRadioButton(tr("range.full_audio"))
        self.radio_custom = QRadioButton(tr("range.custom_range"))
        self.radio_full.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.radio_custom.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.radio_full.setChecked(True)

        self.btn_group_mode.addButton(self.radio_full, 0)
        self.btn_group_mode.addButton(self.radio_custom, 1)

        mode_row.addWidget(self.radio_full)
        mode_row.addWidget(self.radio_custom)
        mode_row.addStretch()
        top_vbox.addLayout(mode_row)

        time_row = QHBoxLayout()
        time_row.setSpacing(8)

        self.lbl_start = QLabel(tr("range.start"))
        time_row.addWidget(self.lbl_start)

        self.time_start = QTimeEdit()
        self.time_start.setDisplayFormat("HH:mm:ss")
        self.time_start.setTime(QTime(0, 0, 0))
        self.time_start.setFixedHeight(32)
        self.time_start.setMinimumWidth(116)
        self.time_start.setFont(fixed_mono_font(12))
        time_row.addWidget(self.time_start)

        time_row.addSpacing(8)

        self.lbl_end = QLabel(tr("range.end"))
        time_row.addWidget(self.lbl_end)

        self.time_end = QTimeEdit()
        self.time_end.setDisplayFormat("HH:mm:ss")
        self.time_end.setTime(QTime(0, 0, 0))
        self.time_end.setFixedHeight(32)
        self.time_end.setMinimumWidth(116)
        self.time_end.setFont(fixed_mono_font(12))
        time_row.addWidget(self.time_end)

        time_row.addStretch()
        top_vbox.addLayout(time_row)

        readout_row = QHBoxLayout()
        readout_row.setSpacing(8)
        self.lbl_selected_length = QLabel(tr("range.selected_zero"))
        self.lbl_selected_length.setFont(fixed_mono_font(12))
        self.lbl_selected_length.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        readout_row.addWidget(self.lbl_selected_length)
        readout_row.addStretch()
        top_vbox.addLayout(readout_row)

        layout.addWidget(self.top_bar)

        # Waveform scrubber + position info
        slider_layout = QVBoxLayout()
        slider_layout.setSpacing(4)

        self.waveform = WaveformScrubberWidget(self)
        slider_layout.addWidget(self.waveform)

        self.lbl_slider_info = QLabel(tr("range.slider_initial"))
        self.lbl_slider_info.setFont(fixed_mono_font(11))
        self.lbl_slider_info.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        slider_layout.addWidget(self.lbl_slider_info)

        layout.addLayout(slider_layout)

        # Wire Signals
        self.radio_full.toggled.connect(self._on_mode_toggled)
        self.radio_custom.toggled.connect(self._on_mode_toggled)
        self.time_start.timeChanged.connect(self._on_time_changed)
        self.time_end.timeChanged.connect(self._on_time_changed)
        self.waveform.range_dragged.connect(self._on_waveform_range_dragged)

        self.apply_theme()
        self._update_container_enabled_state()

    def apply_theme(self) -> None:
        """Apply active ThemePalette tokens to borders and text roles."""
        p = get_palette()
        self.top_bar.setStyleSheet(f"""
            #range_top_bar {{
                background-color: {p.bg_input};
                border: 1px solid {p.border};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_selected_length.setStyleSheet(f"color: {p.text_main};")
        self.lbl_start.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self.lbl_end.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self.lbl_slider_info.setStyleSheet(f"color: {p.text_muted};")
        self.waveform.update()

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        self.radio_full.setText(tr("range.full_audio"))
        self.radio_custom.setText(tr("range.custom_range"))
        self.lbl_start.setText(tr("range.start"))
        self.lbl_end.setText(tr("range.end"))
        self.waveform.retranslate_ui()
        if self._current_track is None:
            self.lbl_selected_length.setText(tr("range.no_track"))
            self.lbl_slider_info.setText(tr("range.position_zero"))
        else:
            self._update_readout()
        self.updateGeometry()

    def cancel_waveform_load(self) -> None:
        """Stop any in-flight background waveform extraction workers safely."""
        self._waveform_request_id += 1
        workers = list(self._waveform_workers)
        self._waveform_workers.clear()
        for worker in workers:
            worker.requestInterruption()
            if worker.isRunning():
                worker.wait(1500)
            worker.deleteLater()

    def _cleanup_worker(self, worker: WaveformLoadWorker) -> None:
        if worker in self._waveform_workers:
            self._waveform_workers.remove(worker)
        worker.deleteLater()

    def set_track(self, track: AudioTrack | None) -> None:
        """Set the active track being inspected and configured."""
        self.cancel_waveform_load()
        self._current_track = track
        if track is None:
            self._total_duration = 0.0
            self.setEnabled(False)
            self.waveform.clear()
            self.lbl_selected_length.setText(tr("range.no_track"))
            self.lbl_slider_info.setText(tr("range.position_zero"))
            return

        self.setEnabled(True)
        self._total_duration = track.info.duration
        self._updating_ui = True

        cfg = track.slice_config
        if cfg.mode == SliceMode.FULL or cfg.is_full(self._total_duration):
            self.radio_full.setChecked(True)
            eff_start = 0.0
            eff_end = self._total_duration
        else:
            self.radio_custom.setChecked(True)
            eff_start = max(0.0, cfg.start_sec)
            eff_end = cfg.effective_end(self._total_duration)

        self._set_qtime(self.time_start, eff_start)
        self._set_qtime(self.time_end, eff_end)

        self.waveform.set_range(eff_start, eff_end, self._total_duration)
        self._updating_ui = False

        self._update_container_enabled_state()
        self._update_readout()
        if self._enable_waveform:
            self._start_waveform_load(track)

    def _start_waveform_load(self, track: AudioTrack) -> None:
        if not track.file_path.is_file():
            self.waveform.set_peaks([])
            return

        key = _cache_key(track.file_path, _DEFAULT_WAVEFORM_BINS)
        if key is not None and key in _WAVEFORM_CACHE:
            self.waveform.set_peaks(_WAVEFORM_CACHE[key])
            return

        req_id = self._waveform_request_id
        self.waveform.set_loading(True)
        worker = WaveformLoadWorker(track.file_path, _DEFAULT_WAVEFORM_BINS, req_id, self)
        worker.peaks_ready.connect(lambda rid, peaks, k=key: self._on_waveform_peaks_ready(rid, peaks, k))
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._waveform_workers.append(worker)
        worker.start()

    def _on_waveform_peaks_ready(
        self,
        request_id: int,
        peaks: list[float],
        key: tuple[str, int, int, int] | None,
    ) -> None:
        if key is not None and peaks:
            if len(_WAVEFORM_CACHE) >= _WAVEFORM_CACHE_MAX:
                _WAVEFORM_CACHE.pop(next(iter(_WAVEFORM_CACHE)))
            _WAVEFORM_CACHE[key] = peaks
        if request_id != self._waveform_request_id:
            return
        self.waveform.set_peaks(peaks)

    def _on_mode_toggled(self) -> None:
        if self._updating_ui:
            return
        self._update_container_enabled_state()
        if self.radio_full.isChecked():
            self._updating_ui = True
            self._set_qtime(self.time_start, 0.0)
            self._set_qtime(self.time_end, self._total_duration)
            self.waveform.set_range(0.0, self._total_duration, self._total_duration)
            self._updating_ui = False
            self._notify_change(0.0, self._total_duration, SliceMode.FULL)
        else:
            start_sec = self._qtime_to_seconds(self.time_start.time())
            end_sec = self._qtime_to_seconds(self.time_end.time())
            self.waveform.set_range(start_sec, end_sec, self._total_duration)
            self._notify_change(start_sec, end_sec, SliceMode.RANGE)
        self._update_readout()

    def _update_container_enabled_state(self) -> None:
        custom_enabled = self.radio_custom.isChecked()
        self.time_start.setEnabled(custom_enabled)
        self.time_end.setEnabled(custom_enabled)

    def _on_time_changed(self) -> None:
        if self._updating_ui:
            return
        start_sec = self._qtime_to_seconds(self.time_start.time())
        end_sec = self._qtime_to_seconds(self.time_end.time())

        if start_sec > self._total_duration:
            start_sec = self._total_duration
            self._set_qtime(self.time_start, start_sec)

        if end_sec > self._total_duration:
            end_sec = self._total_duration
            self._set_qtime(self.time_end, end_sec)

        if end_sec < start_sec:
            end_sec = start_sec
            self._set_qtime(self.time_end, end_sec)

        self._updating_ui = True
        self.waveform.set_range(start_sec, end_sec, self._total_duration)
        self._updating_ui = False

        self._notify_change(start_sec, end_sec, SliceMode.RANGE)
        self._update_readout()

    def _on_waveform_range_dragged(self, start_sec: float, end_sec: float) -> None:
        if self._updating_ui:
            return
        start_clamped = max(0.0, min(start_sec, self._total_duration))
        end_clamped = max(start_clamped, min(end_sec, self._total_duration))
        self._updating_ui = True
        if not self.radio_custom.isChecked():
            self.radio_custom.setChecked(True)
            self._update_container_enabled_state()
        self._set_qtime(self.time_start, round(start_clamped))
        self._set_qtime(self.time_end, round(end_clamped))
        self._updating_ui = False

        self._notify_change(start_clamped, end_clamped, SliceMode.RANGE)
        self._update_readout(start_override=start_clamped, end_override=end_clamped)

    def _notify_change(self, start_sec: float, end_sec: float, mode: SliceMode) -> None:
        if self._current_track is not None:
            self._current_track.slice_config = SliceConfig(
                mode=mode,
                start_sec=start_sec,
                end_sec=end_sec,
            )
        self.range_changed.emit(start_sec, end_sec)

    def _update_readout(
        self,
        start_override: float | None = None,
        end_override: float | None = None,
    ) -> None:
        if self._total_duration <= 0:
            self.lbl_selected_length.setText(tr("range.selected_zero"))
            self.lbl_slider_info.setText(tr("range.position_zero"))
            return

        if self.radio_full.isChecked():
            dur_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(tr("range.selected_full", duration=dur_str))
            self.lbl_slider_info.setText(tr("range.slider_full", duration=dur_str))
        else:
            start_sec = (
                start_override if start_override is not None else self._qtime_to_seconds(self.time_start.time())
            )
            end_sec = end_override if end_override is not None else self._qtime_to_seconds(self.time_end.time())
            dur = max(0.0, end_sec - start_sec)
            s_str = format_seconds(start_sec)
            e_str = format_seconds(end_sec)
            d_str = format_seconds(dur)
            t_str = format_seconds(self._total_duration)
            self.lbl_selected_length.setText(tr("range.selected_custom", duration=d_str))
            self.lbl_slider_info.setText(
                tr("range.slider_custom", start=s_str, end=e_str, duration=d_str, total=t_str)
            )
        self.updateGeometry()

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

        self.setWindowTitle(tr("trim.window_title", filename=track.info.filename))
        self.setMinimumWidth(656)
        self.resize(680, 380)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        p = get_palette()
        title = QLabel(tr("trim.heading", filename=track.info.filename))
        title.setStyleSheet(f"font-weight: 500; font-size: 14px; color: {p.text_main};")
        layout.addWidget(title)

        self.selector = RangeSelectorWidget(self)
        self.selector.set_track(track)
        self.selector.waveform.seek_requested.connect(self._on_waveform_seek)
        layout.addWidget(self.selector)

        # Compact audio preview bar
        preview_bar = QFrame()
        preview_bar.setObjectName("trim_preview_bar")
        preview_bar.setStyleSheet(f"""
            #trim_preview_bar {{
                background-color: {p.bg_input};
                border: 1px solid {p.border};
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

        self.btn_play_pause = QPushButton(tr("trim.play"))
        self.btn_play_pause.setFixedHeight(32)
        self.btn_play_pause.setIcon(load_ui_icon("play"))
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.clicked.connect(self._on_play_pause)
        preview_layout.addWidget(self.btn_play_pause)

        self.btn_play_selection = QPushButton(tr("trim.preview_range"))
        self.btn_play_selection.setFixedHeight(32)
        self.btn_play_selection.setIcon(load_ui_icon("play"))
        self.btn_play_selection.setIconSize(QSize(14, 14))
        self.btn_play_selection.clicked.connect(self._on_play_selection)
        preview_layout.addWidget(self.btn_play_selection)

        preview_layout.addStretch()

        self.lbl_playback_pos = QLabel("00:00:00 / 00:00:00")
        self.lbl_playback_pos.setFont(fixed_mono_font(11))
        self.lbl_playback_pos.setStyleSheet(f"color: {p.text_muted};")
        preview_layout.addWidget(self.lbl_playback_pos)

        layout.addWidget(preview_bar)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = btn_box.button(QDialogButtonBox.Ok)
        cancel_btn = btn_box.button(QDialogButtonBox.Cancel)
        ok_btn.setText(tr("trim.apply"))
        ok_btn.setFixedHeight(32)
        cancel_btn.setText(tr("trim.cancel"))
        cancel_btn.setFixedHeight(32)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        self.selector.range_changed.connect(self._on_range_changed)
        self._init_player()
        self._sync_dialog_size()

    def _sync_dialog_size(self) -> None:
        """Ensure dialog bounds always fit current font metrics without clipping."""
        self.ensurePolished()
        if self.layout() is not None:
            self.layout().activate()
        hint = self.sizeHint().expandedTo(self.minimumSizeHint())
        min_w = max(656, hint.width())
        min_h = max(380, hint.height())
        self.setMinimumSize(min_w, min_h)
        self.resize(max(680, self.width(), min_w), max(408, self.height(), min_h))

    def showEvent(self, event: QShowEvent) -> None:
        self._sync_dialog_size()
        super().showEvent(event)

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
                if hasattr(player, "errorOccurred"):
                    player.errorOccurred.connect(self._on_player_error)
                player.setSource(QUrl.fromLocalFile(str(self.track.file_path)))
                self._player = player
                self._audio_output = audio_output
                has_media = True
            except Exception:
                self._player = None
                self._audio_output = None

        self.btn_play_pause.setEnabled(has_media)
        self.btn_play_selection.setEnabled(has_media)

    def _on_player_error(self, *_args) -> None:
        self._preview_end_ms = None

    def _on_waveform_seek(self, seconds: float) -> None:
        pos_ms = int(round(max(0.0, seconds) * 1000))
        self._preview_end_ms = None
        if self._player is not None:
            try:
                self._player.setPosition(pos_ms)
            except Exception:
                pass
        self._update_position_label(pos_ms)

    def _on_play_pause(self) -> None:
        if self._player is None:
            return
        try:
            if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._player.pause()
            else:
                self._preview_end_ms = None
                self._player.play()
        except Exception:
            pass

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
            try:
                self._player.setPosition(start_ms)
                self._player.pause()
            except Exception:
                pass
            self.selector.waveform.set_playhead(start_sec)
            return

        self._preview_end_ms = end_ms
        self.selector.waveform.set_playhead(start_sec)
        try:
            self._player.setPosition(start_ms)
            self._player.play()
        except Exception:
            pass

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
        self.selector.waveform.set_playhead(position_ms / 1000.0)
        if self._preview_end_ms is not None and position_ms >= self._preview_end_ms:
            self._preview_end_ms = None
            if (
                self._player is not None
                and self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            ):
                self._player.pause()

    def _on_playback_state_changed(self, state: object) -> None:
        if QMediaPlayer is not None and state == QMediaPlayer.PlaybackState.PlayingState:
            self.btn_play_pause.setText(tr("trim.pause"))
            self.btn_play_pause.setIcon(load_ui_icon("pause"))
        else:
            self.btn_play_pause.setText(tr("trim.play"))
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
        self.selector.cancel_waveform_load()
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
