"""Real-time streaming transcript viewer with view switching (Polished vs Raw) and export actions."""

from __future__ import annotations

from dataclasses import replace
import html
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QKeySequence,
    QShortcut,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]

from whisper_gui.audio_utils import format_seconds
from whisper_gui.exporters import export_transcript
from whisper_gui.i18n import display_track_status, tr
from whisper_gui.llm_cleaner import PROMPT_PRESET_IDS, get_llm_error_hint, get_preset_label
from whisper_gui.models import (
    AudioTrack,
    SliceMode,
    TrackStatus,
    TranscriptionConfig,
    TranscriptionResult,
    TranscriptSegment,
)
from whisper_gui.platform_utils import open_path_in_os, reveal_file_in_os
from whisper_gui.ui.theme import (
    fixed_mono_font,
    get_palette,
    load_ui_icon,
    menu_stylesheet,
    style_menu,
)


class TranscriptView(QFrame):
    """Displays real-time streaming transcription segments, progress bar, synced audio playback, and export actions."""

    polish_requested = Signal()
    preset_selected = Signal(str)
    llm_settings_requested = Signal()
    track_exported = Signal(object)
    playback_position_changed = Signal(float)  # relative seconds within transcript
    segment_activated = Signal(int)            # active segment index

    _PLAYBACK_RATES: tuple[float, ...] = (0.75, 1.0, 1.25, 1.5, 2.0)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_docx_path: Path | None = None
        self._current_track: AudioTrack | None = None
        self._current_result: TranscriptionResult | None = None
        self._current_config: TranscriptionConfig | None = None
        self._exported_paths: dict[str, Path] = {}
        self._raw_segments: list[TranscriptSegment] = []
        self._polished_text: str | None = None
        self._polished_model_name: str = ""
        self._active_preset: str | None = "default"
        self._polish_error_msg: str = ""
        self._active_mode: str = "raw"  # "raw" or "polished"
        self._updating_text: bool = False
        self._raw_edited: bool = False
        self._raw_edited_text: str | None = None
        self._raw_segments_stale: bool = False

        # Audio playback state
        self._player = None
        self._audio_output = None
        self._loaded_audio_path: Path | None = None
        self._slice_start_ms: int = 0
        self._slice_end_ms: int = 0
        self._playback_duration_ms: int = 0
        self._slider_dragging: bool = False
        self._updating_slider: bool = False
        self._playback_rate_idx: int = 1  # 1.0x
        self._active_segment_idx: int | None = None
        self._pressed_seek_block: int | None = None
        self._pending_seek_abs_ms: int | None = None
        self._pending_seek_deadline: float = 0.0

        self.setObjectName("transcript_view")
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 12, 16, 12)

        # Header: Title + Status + Metrics
        prog_header = QHBoxLayout()
        prog_header.setSpacing(8)

        self.lbl_section = QLabel(tr("transcript.title"))
        prog_header.addWidget(self.lbl_section)

        self.lbl_status = QLabel(tr("transcript.idle"))
        prog_header.addWidget(self.lbl_status)

        prog_header.addStretch()
        self.lbl_metrics = QLabel("")
        self.lbl_metrics.setFont(fixed_mono_font(11))
        self.lbl_metrics.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        prog_header.addWidget(self.lbl_metrics)
        layout.addLayout(prog_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        layout.addWidget(self.progress_bar)

        # View mode selector bar (Raw vs Polished segmented control)
        mode_bar = QHBoxLayout()
        mode_bar.setSpacing(4)

        self.view_btn_group = QButtonGroup(self)
        self.btn_view_raw = QPushButton(tr("transcript.raw"))
        self.btn_view_raw.setCheckable(True)
        self.btn_view_raw.setChecked(True)
        self.btn_view_raw.setFixedHeight(32)
        self.view_btn_group.addButton(self.btn_view_raw)
        mode_bar.addWidget(self.btn_view_raw)

        self.btn_view_polished = QPushButton(tr("transcript.polished"))
        self.btn_view_polished.setCheckable(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_view_polished.setFixedHeight(32)
        self.view_btn_group.addButton(self.btn_view_polished)
        mode_bar.addWidget(self.btn_view_polished)

        self.btn_polish = QPushButton(tr("transcript.polish"))
        self.btn_polish.setEnabled(False)
        self.btn_polish.setFixedHeight(32)
        self.btn_polish.setToolTip(tr("transcript.polish_tooltip"))
        mode_bar.addWidget(self.btn_polish)

        self.btn_polish_preset = QPushButton()
        self.btn_polish_preset.setObjectName("btn_polish_preset")
        self.btn_polish_preset.setFixedSize(32, 32)
        self.btn_polish_preset.setIconSize(QSize(14, 14))
        self.polish_preset_menu = style_menu(QMenu(self))
        self.polish_preset_group = QActionGroup(self)
        self.polish_preset_group.setExclusive(True)
        self.polish_preset_actions: dict[str, QAction] = {}
        for preset_id in PROMPT_PRESET_IDS:
            act = self.polish_preset_menu.addAction(get_preset_label(preset_id))
            act.setCheckable(True)
            act.setData(preset_id)
            act.triggered.connect(lambda _checked=False, pid=preset_id: self._on_preset_action_triggered(pid))
            self.polish_preset_group.addAction(act)
            self.polish_preset_actions[preset_id] = act
        self.polish_preset_menu.addSeparator()
        self._act_open_llm_settings = self.polish_preset_menu.addAction(
            tr("transcript.preset_open_settings")
        )
        self._act_open_llm_settings.triggered.connect(self.llm_settings_requested.emit)
        mode_bar.addWidget(self.btn_polish_preset)

        self.lbl_view_hint = QLabel("")
        self.lbl_view_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_view_hint.setMinimumWidth(0)
        mode_bar.addWidget(self.lbl_view_hint, stretch=1)

        self.btn_find = QPushButton(tr("transcript.find"))
        self.btn_find.setCheckable(True)
        self.btn_find.setFixedHeight(32)
        self.btn_find.setToolTip(tr("transcript.find_tooltip"))
        mode_bar.addWidget(self.btn_find)
        layout.addLayout(mode_bar)

        # Collapsible Find bar (hidden by default)
        self.find_bar = QFrame()
        self.find_bar.setObjectName("find_bar")
        self.find_bar.setVisible(False)
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(0, 0, 0, 0)
        find_layout.setSpacing(4)

        self.txt_find = QLineEdit()
        self.txt_find.setFixedHeight(32)
        self.txt_find.setPlaceholderText(tr("transcript.find_placeholder"))
        self.txt_find.setClearButtonEnabled(True)
        find_layout.addWidget(self.txt_find, stretch=1)

        self.btn_find_prev = QPushButton(tr("transcript.find_prev"))
        self.btn_find_prev.setFixedHeight(32)
        self.btn_find_prev.setToolTip(tr("transcript.find_prev_tooltip"))
        self.btn_find_prev.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        find_layout.addWidget(self.btn_find_prev)

        self.btn_find_next = QPushButton(tr("transcript.find_next"))
        self.btn_find_next.setFixedHeight(32)
        self.btn_find_next.setToolTip(tr("transcript.find_next_tooltip"))
        self.btn_find_next.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        find_layout.addWidget(self.btn_find_next)

        self.lbl_find_status = QLabel("")
        self.lbl_find_status.setFont(fixed_mono_font(11))
        find_layout.addWidget(self.lbl_find_status)

        self.btn_find_close = QPushButton()
        self.btn_find_close.setFixedSize(32, 32)
        self.btn_find_close.setToolTip(tr("transcript.find_close_tooltip"))
        self.btn_find_close.setStyleSheet("padding: 0px;")
        find_layout.addWidget(self.btn_find_close)

        layout.addWidget(self.find_bar)

        # Inline LLM error recovery bar (hidden unless polishing fails)
        self.polish_error_bar = QFrame()
        self.polish_error_bar.setObjectName("polish_error_bar")
        self.polish_error_bar.setVisible(False)
        err_layout = QHBoxLayout(self.polish_error_bar)
        err_layout.setContentsMargins(12, 8, 12, 8)
        err_layout.setSpacing(8)

        self.lbl_polish_error = QLabel("")
        self.lbl_polish_error.setWordWrap(True)
        err_layout.addWidget(self.lbl_polish_error, stretch=1)

        self.btn_polish_retry = QPushButton(tr("transcript.polish_retry"))
        self.btn_polish_retry.setFixedHeight(32)
        err_layout.addWidget(self.btn_polish_retry)

        self.btn_polish_settings = QPushButton(tr("transcript.polish_settings"))
        self.btn_polish_settings.setFixedHeight(32)
        err_layout.addWidget(self.btn_polish_settings)

        self.btn_polish_err_close = QPushButton()
        self.btn_polish_err_close.setFixedSize(32, 32)
        self.btn_polish_err_close.setToolTip(tr("transcript.polish_error_dismiss"))
        self.btn_polish_err_close.setStyleSheet("padding: 0px;")
        err_layout.addWidget(self.btn_polish_err_close)

        layout.addWidget(self.polish_error_bar)

        # Compact synced audio playback bar (visible when a track is loaded)
        self.playback_bar = QFrame()
        self.playback_bar.setObjectName("transcript_playback_bar")
        self.playback_bar.setVisible(False)
        pb_layout = QHBoxLayout(self.playback_bar)
        pb_layout.setContentsMargins(0, 4, 0, 4)
        pb_layout.setSpacing(8)

        self.btn_play_pause = QPushButton(tr("transcript.play"))
        self.btn_play_pause.setFixedHeight(32)
        self.btn_play_pause.setIconSize(QSize(14, 14))
        self.btn_play_pause.setToolTip(tr("transcript.play_tooltip"))
        pb_layout.addWidget(self.btn_play_pause)

        self.slider_playback = QSlider(Qt.Horizontal)
        self.slider_playback.setRange(0, 1000)
        self.slider_playback.setValue(0)
        pb_layout.addWidget(self.slider_playback, stretch=1)

        self.lbl_playback_time = QLabel("00:00 / 00:00")
        self.lbl_playback_time.setFont(fixed_mono_font(11))
        pb_layout.addWidget(self.lbl_playback_time)

        self.btn_playback_speed = QPushButton("1.0x")
        self.btn_playback_speed.setFixedHeight(32)
        self.btn_playback_speed.setFont(fixed_mono_font(11))
        self.btn_playback_speed.setToolTip(tr("transcript.speed_tooltip"))
        pb_layout.addWidget(self.btn_playback_speed)

        layout.addWidget(self.playback_bar)

        # Text stream display
        self.txt_display = QTextEdit()
        self.txt_display.setReadOnly(False)
        self.txt_display.setPlaceholderText(tr("transcript.placeholder"))
        self.txt_display.setMinimumHeight(140)
        self.txt_display.viewport().setMouseTracking(True)
        self.txt_display.viewport().installEventFilter(self)
        layout.addWidget(self.txt_display, stretch=1)

        # Bottom action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_copy = QPushButton(tr("transcript.copy"))
        self.btn_copy.setFixedHeight(32)
        self.btn_copy.setStyleSheet("padding: 4px 12px;")
        btn_layout.addWidget(self.btn_copy)

        self.btn_export = QPushButton(tr("transcript.export"))
        self.btn_export.setFixedHeight(32)
        self.btn_export.setEnabled(False)
        self.btn_open_docx = self.btn_export  # Compatibility alias

        self.export_menu = style_menu(QMenu(self))

        self._act_docx = self.export_menu.addAction(tr("transcript.menu_docx"))
        self._act_docx.triggered.connect(lambda: self._on_export_format("docx"))

        self._act_pdf = self.export_menu.addAction(tr("transcript.menu_pdf"))
        self._act_pdf.triggered.connect(lambda: self._on_export_format("pdf"))

        self._act_md = self.export_menu.addAction(tr("transcript.menu_md"))
        self._act_md.triggered.connect(lambda: self._on_export_format("md"))

        self._act_txt = self.export_menu.addAction(tr("transcript.menu_txt"))
        self._act_txt.triggered.connect(lambda: self._on_export_format("txt"))

        self._act_srt = self.export_menu.addAction(tr("transcript.menu_srt"))
        self._act_srt.triggered.connect(lambda: self._on_export_format("srt"))

        self._act_vtt = self.export_menu.addAction(tr("transcript.menu_vtt"))
        self._act_vtt.triggered.connect(lambda: self._on_export_format("vtt"))

        self.export_menu.addSeparator()

        self._act_folder = self.export_menu.addAction(tr("transcript.menu_open_folder"))
        self._act_folder.triggered.connect(self._open_containing_folder)

        self.btn_export.setMenu(self.export_menu)
        btn_layout.addWidget(self.btn_export)

        self.btn_open_folder = QPushButton(tr("transcript.open_folder"))
        self.btn_open_folder.setFixedHeight(32)
        self.btn_open_folder.setStyleSheet("padding: 4px 12px;")
        self.btn_open_folder.setEnabled(False)
        btn_layout.addWidget(self.btn_open_folder)

        self.btn_clear = QPushButton(tr("transcript.clear"))
        self.btn_clear.setFixedHeight(32)
        self.btn_clear.setStyleSheet("padding: 4px 12px;")
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.apply_theme()

        # Shortcuts
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.activated.connect(self._toggle_find_bar)
        self._find_esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self.find_bar)
        self._find_esc_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._find_esc_shortcut.activated.connect(self._hide_find_bar)

        # Connect signals
        self.btn_view_raw.clicked.connect(lambda: self._on_mode_button_clicked("raw"))
        self.btn_polish.clicked.connect(self.polish_requested.emit)
        self.btn_polish_preset.clicked.connect(self._open_preset_menu)
        self.btn_polish_retry.clicked.connect(self.polish_requested.emit)
        self.btn_polish_settings.clicked.connect(self.llm_settings_requested.emit)
        self.btn_polish_err_close.clicked.connect(self.clear_polish_error)
        self.btn_view_polished.clicked.connect(lambda: self._on_mode_button_clicked("polished"))
        self.sync_polish_preset(self._active_preset)
        self.btn_find.clicked.connect(self._toggle_find_bar)
        self.txt_find.textChanged.connect(self._on_find_text_changed)
        self.txt_find.returnPressed.connect(self._find_next)
        self.btn_find_next.clicked.connect(self._find_next)
        self.btn_find_prev.clicked.connect(self._find_prev)
        self.btn_find_close.clicked.connect(self._hide_find_bar)
        self.txt_display.textChanged.connect(self._on_text_changed)
        self.btn_open_folder.clicked.connect(self._open_containing_folder)
        self.btn_copy.clicked.connect(self._copy_text)
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        self.btn_play_pause.clicked.connect(self.toggle_playback)
        self.btn_playback_speed.clicked.connect(self._cycle_playback_speed)
        self.slider_playback.sliderPressed.connect(self._on_slider_pressed)
        self.slider_playback.sliderMoved.connect(self._on_slider_moved)
        self.slider_playback.sliderReleased.connect(self._on_slider_released)
        self.slider_playback.valueChanged.connect(self._on_slider_value_changed)

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        self.lbl_section.setText(tr("transcript.title"))
        if self._current_track is None:
            self.lbl_status.setText(tr("transcript.idle"))
            self.lbl_metrics.setText("")
        else:
            self.lbl_status.setText(
                display_track_status(self._current_track.status_message, self._current_track.status)
            )
            if self._current_track.status in (
                TrackStatus.COMPLETED,
                TrackStatus.CANCELLED,
                TrackStatus.ERROR,
            ):
                self.lbl_metrics.setText("")
        self.btn_view_raw.setText(tr("transcript.raw"))
        self.btn_view_polished.setText(tr("transcript.polished"))
        for pid, act in self.polish_preset_actions.items():
            act.setText(get_preset_label(pid))
        self._act_open_llm_settings.setText(tr("transcript.preset_open_settings"))
        self.sync_polish_preset(self._active_preset)
        self._update_polish_button_state()
        if self._polished_text and self._polished_text.strip():
            info = (
                tr("transcript.polished_with_model", model=self._polished_model_name)
                if self._polished_model_name
                else tr("transcript.polished_with_llm")
            )
            self.lbl_view_hint.setText(info)
        self.btn_polish_retry.setText(tr("transcript.polish_retry"))
        self.btn_polish_settings.setText(tr("transcript.polish_settings"))
        self.btn_polish_err_close.setToolTip(tr("transcript.polish_error_dismiss"))
        if self._polish_error_msg and self.polish_error_bar.isVisible():
            self.show_polish_error(self._polish_error_msg)
        self.btn_find.setText(tr("transcript.find"))
        self.btn_find.setToolTip(tr("transcript.find_tooltip"))
        self.txt_find.setPlaceholderText(tr("transcript.find_placeholder"))
        self.btn_find_prev.setText(tr("transcript.find_prev"))
        self.btn_find_prev.setToolTip(tr("transcript.find_prev_tooltip"))
        self.btn_find_next.setText(tr("transcript.find_next"))
        self.btn_find_next.setToolTip(tr("transcript.find_next_tooltip"))
        self.btn_find_close.setToolTip(tr("transcript.find_close_tooltip"))
        if self.find_bar.isVisible() and self.txt_find.text():
            self._update_find_status(self.txt_find.text())
        self.txt_display.setPlaceholderText(tr("transcript.placeholder"))
        self.btn_copy.setText(tr("transcript.copy"))
        self.btn_export.setText(tr("transcript.export"))
        self._act_docx.setText(tr("transcript.menu_docx"))
        self._act_pdf.setText(tr("transcript.menu_pdf"))
        self._act_md.setText(tr("transcript.menu_md"))
        self._act_txt.setText(tr("transcript.menu_txt"))
        self._act_srt.setText(tr("transcript.menu_srt"))
        self._act_vtt.setText(tr("transcript.menu_vtt"))
        self._act_folder.setText(tr("transcript.menu_open_folder"))
        self.btn_open_folder.setText(tr("transcript.open_folder"))
        self.btn_clear.setText(tr("transcript.clear"))
        self._update_play_pause_button()
        self.btn_playback_speed.setToolTip(tr("transcript.speed_tooltip"))

    def apply_theme(self) -> None:
        """Apply the active theme palette to all transcript view elements."""
        p = get_palette()
        self.setStyleSheet(f"""
            #transcript_view {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            #find_bar {{
                background: transparent;
                border: none;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_section.setStyleSheet(f"font-weight: 500; color: {p.text_main}; font-size: 13px;")
        self.lbl_status.setStyleSheet(f"color: {p.text_secondary}; font-size: 12px;")
        self.lbl_metrics.setStyleSheet(f"color: {p.text_muted};")
        self.lbl_view_hint.setStyleSheet(f"color: {p.text_muted}; font-size: 12px; padding-left: 8px;")
        self.lbl_find_status.setStyleSheet(f"color: {p.text_muted}; padding: 0 4px;")
        self.btn_find_close.setIcon(load_ui_icon("close"))
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {p.border};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {p.primary};
                border-radius: 2px;
            }}
        """)

        self.playback_bar.setStyleSheet("""
            #transcript_playback_bar {
                background: transparent;
                border: none;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        self.lbl_playback_time.setStyleSheet(f"color: {p.text_muted};")
        pb_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {p.text_main};
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid {p.border};
                border-radius: 8px;
            }}
            QPushButton:hover:enabled {{
                background-color: {p.bg_raised};
                border-color: {p.border_light};
            }}
            QPushButton:disabled {{
                color: {p.text_hint};
                background-color: transparent;
            }}
        """
        self.btn_play_pause.setStyleSheet(pb_btn_style)
        self.btn_playback_speed.setStyleSheet(pb_btn_style)
        self._update_play_pause_button()

        seg_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {p.text_muted};
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 500;
                border: 1px solid {p.border};
                border-radius: 8px;
            }}
            QPushButton:hover:enabled {{
                color: {p.text_main};
                background-color: {p.bg_raised};
            }}
            QPushButton:checked {{
                background-color: {p.bg_raised};
                border: 1px solid {p.border_light};
                color: {p.text_main};
            }}
            QPushButton:disabled {{
                color: {p.text_hint};
                background-color: transparent;
            }}
        """
        for btn in (self.btn_view_raw, self.btn_view_polished, self.btn_polish, self.btn_find):
            btn.setStyleSheet(seg_btn_style)
            btn.setFixedHeight(32)

        self.btn_polish_preset.setStyleSheet(
            seg_btn_style + "\nQPushButton { padding: 0px; }"
        )
        self.btn_polish_preset.setIcon(load_ui_icon("chevron-down"))

        self.polish_error_bar.setStyleSheet(f"""
            #polish_error_bar {{
                background-color: {p.bg_raised};
                border: 1px solid {p.border};
                border-radius: 8px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_polish_error.setStyleSheet(f"color: {p.negative}; font-size: 12px;")
        self.btn_polish_err_close.setIcon(load_ui_icon("close"))

        menu_style = menu_stylesheet(p)
        self.polish_preset_menu.setStyleSheet(menu_style)

        self.txt_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {p.bg_input};
                color: {p.text_main};
                font-size: 13px;
                border: 1px solid {p.border};
                border-radius: 8px;
                padding: 12px;
            }}
        """)
        self.btn_export.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 24px 4px 12px;
            }}
            QPushButton::menu-indicator {{
                image: url({p.chevron_url});
                subcontrol-origin: padding;
                subcontrol-position: right center;
                right: 8px;
                width: 14px;
                height: 14px;
            }}
        """)
        self.export_menu.setStyleSheet(menu_style)
        if (
            self._raw_segments
            or self._raw_edited
            or self._polished_text is not None
            or (self._current_result and self._current_result.full_text)
        ):
            self._switch_view(self._active_mode, force=True)
        self._highlight_active_segment()

    def _open_preset_menu(self) -> None:
        pos = self.btn_polish_preset.mapToGlobal(QPoint(0, self.btn_polish_preset.height() + 4))
        self.polish_preset_menu.exec(pos)

    def _on_preset_action_triggered(self, preset_id: str) -> None:
        self.sync_polish_preset(preset_id)
        self.preset_selected.emit(preset_id)

    def sync_polish_preset(self, preset_id: str | None) -> None:
        """Update preset menu selection and tooltips without emitting preset_selected."""
        self._active_preset = preset_id
        for pid, act in self.polish_preset_actions.items():
            act.setChecked(preset_id == pid)
        label = get_preset_label(preset_id) if preset_id else tr("llm.preset_custom")
        self.btn_polish_preset.setToolTip(tr("transcript.preset_tooltip", name=label))
        self.btn_polish.setToolTip(tr("transcript.polish_tooltip_preset", name=label))

    def show_polish_error(self, error_msg: str) -> None:
        """Show the inline non-blocking LLM error recovery banner with actionable hint."""
        self._polish_error_msg = error_msg or ""
        if not self._polish_error_msg.strip():
            self.clear_polish_error()
            return
        _category, hint = get_llm_error_hint(self._polish_error_msg)
        self.lbl_polish_error.setText(f"{self._polish_error_msg} {hint}".strip())
        self.polish_error_bar.setVisible(True)

    def clear_polish_error(self) -> None:
        """Hide the inline LLM error recovery banner."""
        self._polish_error_msg = ""
        self.lbl_polish_error.setText("")
        self.polish_error_bar.setVisible(False)

    def _toggle_find_bar(self) -> None:
        if self.find_bar.isVisible():
            self._hide_find_bar()
        else:
            self._show_find_bar()

    def _show_find_bar(self) -> None:
        self.find_bar.setVisible(True)
        self.btn_find.setChecked(True)
        self.txt_find.setFocus()
        self.txt_find.selectAll()
        if self.txt_find.text():
            self._update_find_status(self.txt_find.text())

    def _hide_find_bar(self) -> None:
        self.find_bar.setVisible(False)
        self.btn_find.setChecked(False)
        self.txt_display.setFocus()

    def _on_find_text_changed(self, query: str) -> None:
        if not query:
            self.lbl_find_status.setText("")
            return
        cursor = self.txt_display.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.txt_display.setTextCursor(cursor)
        self.txt_display.find(query)
        self._update_find_status(query)

    def _find_next(self) -> None:
        self._find_match(backward=False)

    def _find_prev(self) -> None:
        self._find_match(backward=True)

    def _find_match(self, backward: bool = False) -> None:
        query = self.txt_find.text()
        if not query:
            self.lbl_find_status.setText("")
            return
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlags()
        found = self.txt_display.find(query, flags)
        if not found:
            cursor = self.txt_display.textCursor()
            cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            self.txt_display.setTextCursor(cursor)
            self.txt_display.find(query, flags)
        self._update_find_status(query)

    def _update_find_status(self, query: str) -> None:
        text_lower = self.txt_display.toPlainText().lower()
        q_lower = query.lower()
        positions: list[int] = []
        start = 0
        while True:
            idx = text_lower.find(q_lower, start)
            if idx == -1:
                break
            positions.append(idx)
            start = idx + max(1, len(q_lower))
        if not positions:
            self.lbl_find_status.setText(tr("transcript.find_zero"))
            return
        sel_start = self.txt_display.textCursor().selectionStart()
        match_num = positions.index(sel_start) + 1 if sel_start in positions else 1
        self.lbl_find_status.setText(tr("transcript.find_count", current=match_num, total=len(positions)))

    def invalidate_document_exports(self) -> None:
        """Clear cached document export paths so the next export regenerates them."""
        for fmt in ("docx", "pdf", "md", "txt"):
            self._exported_paths.pop(fmt, None)
        self._current_docx_path = None
        if self._current_result is not None:
            self._current_result.docx_path = None
            self._current_result.pdf_path = None
            self._current_result.md_path = None
            self._current_result.txt_path = None

    def set_export_config(self, config: TranscriptionConfig) -> None:
        """Keep export config synced with Settings/LLM panels and drop stale caches on option changes."""
        prev = self._current_config
        self._current_config = config
        if prev is None:
            return
        prev_raw = prev.llm_config.include_raw_in_docx if prev.llm_config else True
        new_raw = config.llm_config.include_raw_in_docx if config.llm_config else True
        if (
            prev.include_timestamps_in_docx != config.include_timestamps_in_docx
            or prev_raw != new_raw
            or prev.output_dir != config.output_dir
        ):
            self.invalidate_document_exports()
            if prev.output_dir != config.output_dir:
                self._exported_paths.pop("srt", None)
                self._exported_paths.pop("vtt", None)

    def _on_text_changed(self) -> None:
        if self._updating_text:
            return
        edited = self.txt_display.toPlainText()
        self._exported_paths.clear()
        self.invalidate_document_exports()
        if self._active_mode == "polished":
            self._polished_text = edited
            if self._current_result is not None:
                self._current_result.polished_text = edited
            self._update_polish_button_state()
        else:
            self._raw_edited = True
            self._raw_edited_text = edited
            self._sync_raw_edits(edited)
            self._update_polish_button_state()

    def _sync_raw_edits(self, edited: str) -> None:
        lines = [line for line in edited.splitlines() if line.strip()]
        if (
            self._raw_segments
            and len(lines) == len(self._raw_segments)
            and all(line.startswith(seg.formatted_timerange) for line, seg in zip(lines, self._raw_segments))
        ):
            for line, seg in zip(lines, self._raw_segments):
                seg.text = line[len(seg.formatted_timerange):].strip()
            self._raw_segments_stale = False
            clean_full = " ".join(seg.text for seg in self._raw_segments if seg.text)
            if self._current_result is not None:
                self._current_result.segments = self._raw_segments
                self._current_result.full_text = clean_full
                self._current_result.raw_segments_stale = False
        else:
            self._raw_segments_stale = True
            if self._current_result is not None:
                self._current_result.full_text = edited
                self._current_result.raw_segments_stale = True

    def set_status(self, message: str) -> None:
        """Update the status label."""
        self.lbl_status.setText(message)

    def set_progress(self, percent: int, metrics_text: str = "") -> None:
        """Update the progress bar and metrics; negative percent switches to indeterminate busy state."""
        if percent < 0:
            if self.progress_bar.maximum() != 0:
                self.progress_bar.setRange(0, 0)
        else:
            if self.progress_bar.minimum() != 0 or self.progress_bar.maximum() != 100:
                self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, percent)))
        if metrics_text:
            self.lbl_metrics.setText(metrics_text)

    def _format_segment_html(self, segment: TranscriptSegment) -> str:
        ts_escaped = html.escape(segment.formatted_timerange)
        text_escaped = html.escape(segment.text)
        p = get_palette()
        ts_html = (
            f"<span style='color: {p.primary}; font-family: monospace; "
            f"font-weight: 500;'>{ts_escaped}</span>"
        )
        text_html = f" <span style='color: {p.text_main};'>{text_escaped}</span>"
        return f"{ts_html}{text_html}"

    def append_segment(self, segment: TranscriptSegment) -> None:
        """Append a newly streamed transcription segment."""
        self._raw_segments.append(segment)
        if self._active_mode == "raw":
            self._updating_text = True
            try:
                cursor = self.txt_display.textCursor()
                cursor.movePosition(QTextCursor.End)
                if self.txt_display.document().blockCount() > 1 or bool(self.txt_display.toPlainText()):
                    cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                cursor.insertHtml(self._format_segment_html(segment))
                self.txt_display.setTextCursor(cursor)
                self.txt_display.ensureCursorVisible()
            finally:
                self._updating_text = False

    def _update_polish_button_state(self) -> None:
        has_raw = bool(
            self._raw_segments
            or (self._current_result and (self._current_result.full_text or "").strip())
            or (self._raw_edited_text and self._raw_edited_text.strip())
        )
        if self._current_result is not None:
            has_polished = bool(
                self._current_result.polished_text and self._current_result.polished_text.strip()
            )
        else:
            has_polished = bool(self._polished_text and self._polished_text.strip())
        self.btn_polish.setEnabled(has_raw)
        self.btn_polish.setText(tr("transcript.repolish") if has_polished else tr("transcript.polish"))

    def set_polished_text(self, text: str, model_name: str = "") -> None:
        """Store polished text and switch view to it."""
        self.clear_polish_error()
        self._polished_text = text
        self._polished_model_name = model_name
        self.btn_view_polished.setEnabled(bool(text.strip()))
        if text.strip():
            self.btn_view_polished.setChecked(True)
            self._switch_view("polished", force=True)
            info = (
                tr("transcript.polished_with_model", model=model_name)
                if model_name
                else tr("transcript.polished_with_llm")
            )
            self.lbl_view_hint.setText(info)
        self._update_polish_button_state()

    def _on_mode_button_clicked(self, mode: str) -> None:
        if mode == self._active_mode:
            return
        self._switch_view(mode)

    def _switch_view(self, mode: str, force: bool = False) -> None:
        if mode == self._active_mode and not force and self.txt_display.toPlainText():
            return
        self._active_mode = mode
        self._updating_text = True
        try:
            self.txt_display.clear()

            if mode == "polished" and self._polished_text is not None:
                self.txt_display.setPlainText(self._polished_text)
            elif self._raw_segments_stale and self._raw_edited_text is not None:
                self.txt_display.setPlainText(self._raw_edited_text)
            elif self._raw_segments:
                cursor = self.txt_display.textCursor()
                for idx, seg in enumerate(self._raw_segments):
                    if idx > 0:
                        cursor.insertBlock(QTextBlockFormat(), QTextCharFormat())
                    cursor.insertHtml(self._format_segment_html(seg))
                self.txt_display.setTextCursor(cursor)
            elif self._current_result and self._current_result.full_text:
                self.txt_display.setPlainText(self._current_result.full_text)
        finally:
            self._updating_text = False
        self._highlight_active_segment()

    def load_track(
        self,
        track: AudioTrack | None,
        config: TranscriptionConfig | None = None,
    ) -> None:
        """Load a track's transcript, view mode, export state, and status into the viewer."""
        self.clear_view()
        if track is None:
            self.set_status(tr("transcript.idle"))
            return

        if track.result is None:
            self._current_track = track
            self._current_config = config
            self.set_status(display_track_status(track.status_message, track.status))
            self.set_progress(track.progress_percent)
            self._load_track_audio(track)
            return

        result = track.result
        self._raw_segments = list(result.segments)
        self._polished_text = result.polished_text
        self._raw_segments_stale = bool(result.raw_segments_stale)
        if self._raw_segments_stale:
            self._raw_edited = True
            self._raw_edited_text = result.full_text
        self.set_completed_track(track, result, config)

        if result.polished_text and result.polished_text.strip():
            self.set_polished_text(result.polished_text, result.llm_model_used or "")
        else:
            self.btn_view_polished.setEnabled(False)
            self.btn_view_raw.setChecked(True)
            self._switch_view("raw", force=True)
            if result.llm_error:
                self.show_polish_error(result.llm_error)

        status_text = display_track_status(track.status_message, track.status)
        self.set_status(status_text)
        self.set_progress(track.progress_percent or 100)

    def set_completed_track(
        self,
        track: AudioTrack,
        result: TranscriptionResult,
        config: TranscriptionConfig | None = None,
    ) -> None:
        """Store active completed track and result for on-demand multi-format export."""
        self._current_track = track
        self._current_result = result
        self._current_config = config

        if self._raw_segments_stale and self._raw_edited_text is not None:
            result.raw_segments_stale = True
            result.full_text = self._raw_edited_text
        elif self._raw_edited and self._raw_segments:
            result.segments = list(self._raw_segments)
            result.full_text = " ".join(seg.text for seg in self._raw_segments if seg.text)

        if not self._raw_edited:
            if result.docx_path:
                self._current_docx_path = result.docx_path
                self._exported_paths["docx"] = result.docx_path
            if result.pdf_path:
                self._exported_paths["pdf"] = result.pdf_path
            if result.md_path:
                self._exported_paths["md"] = result.md_path
            if result.txt_path:
                self._exported_paths["txt"] = result.txt_path

        self.btn_export.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        self._update_polish_button_state()
        if self._loaded_audio_path != track.file_path:
            self._load_track_audio(track)

    def set_completed_docx(self, docx_path: Path) -> None:
        """Mark document as ready and enable export/folder actions."""
        self._current_docx_path = docx_path
        self._exported_paths["docx"] = docx_path
        self.btn_export.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        self._update_polish_button_state()

    def _on_clear_clicked(self) -> None:
        """Prompt confirmation if content exists before clearing transcript view."""
        has_content = bool(
            self.txt_display.toPlainText().strip()
            or self._raw_segments
            or self._current_track
        )
        if has_content:
            reply = QMessageBox.question(
                self,
                tr("transcript.clear_title"),
                tr("transcript.clear_body"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        self.clear_view()

    def clear_view(self) -> None:
        """Clear transcription output and reset progress."""
        self.release_player()
        self._raw_segments.clear()
        self._polished_text = None
        self._polished_model_name = ""
        self._active_mode = "raw"
        self._raw_edited = False
        self._raw_edited_text = None
        self._raw_segments_stale = False
        self._current_track = None
        self._current_result = None
        self._current_config = None
        self._exported_paths.clear()
        self._current_docx_path = None
        self._active_segment_idx = None
        self._pressed_seek_block = None

        self._updating_text = True
        try:
            self.txt_display.clear()
            self.txt_display.setExtraSelections([])
        finally:
            self._updating_text = False
        self.playback_bar.setVisible(False)
        self.lbl_playback_time.setText("00:00 / 00:00")
        self._updating_slider = True
        try:
            self.slider_playback.setRange(0, 1000)
            self.slider_playback.setValue(0)
        finally:
            self._updating_slider = False
        self.lbl_find_status.setText("")
        self.clear_polish_error()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.lbl_status.setText(tr("transcript.idle"))
        self.lbl_metrics.setText("")
        self.lbl_view_hint.setText("")
        self.btn_view_raw.setChecked(True)
        self.btn_view_polished.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_open_folder.setEnabled(False)
        self._update_polish_button_state()

    def _on_export_format(self, fmt: str) -> None:
        """Export or open the requested format: 'docx', 'pdf', 'md', 'txt', 'srt', 'vtt'."""
        try:
            # 1. Open if already exported and exists
            existing_path = self._exported_paths.get(fmt)
            if existing_path and existing_path.exists():
                success = open_path_in_os(existing_path)
                if success:
                    self.lbl_status.setText(tr("transcript.status_opened", name=existing_path.name))
                else:
                    self.lbl_status.setText(tr("transcript.status_saved", name=existing_path.name))
                return

            # 2. Determine target path
            if self._current_track:
                target_dir = self._current_config.output_dir if self._current_config else None
                out_path = self._current_track.effective_export_path(fmt, target_dir)
            elif self._current_docx_path:
                out_path = self._current_docx_path.with_suffix(f".{fmt}")
            else:
                out_path = Path.home() / f"transcript.{fmt}"

            # 3. Perform export
            if self._current_result is not None:
                stale = self._raw_segments_stale or self._current_result.raw_segments_stale
                result_obj = (
                    replace(self._current_result, segments=[])
                    if stale
                    else self._current_result
                )
            else:
                raw_text = (
                    self._raw_edited_text
                    if self._raw_edited and self._raw_edited_text is not None
                    else ("" if self._active_mode == "polished" else self.txt_display.toPlainText())
                )
                result_obj = TranscriptionResult(
                    full_text=raw_text,
                    segments=[] if self._raw_segments_stale else self._raw_segments,
                    polished_text=self._polished_text,
                )
            saved_path = export_transcript(
                format_name=fmt,
                output_path=out_path,
                track_info=self._current_track.info if self._current_track else None,
                slice_config=self._current_track.slice_config if self._current_track else None,
                transcription_config=self._current_config,
                result=result_obj,
            )
            self._exported_paths[fmt] = saved_path
            if fmt == "docx":
                self._current_docx_path = saved_path
            if self._current_result is not None:
                if fmt == "docx":
                    self._current_result.docx_path = saved_path
                elif fmt == "pdf":
                    self._current_result.pdf_path = saved_path
                elif fmt == "md":
                    self._current_result.md_path = saved_path
                elif fmt == "txt":
                    self._current_result.txt_path = saved_path

            if self._current_track is not None:
                self.track_exported.emit(self._current_track)

            # 4. Open with default OS viewer
            success = open_path_in_os(saved_path)
            if success:
                self.lbl_status.setText(tr("transcript.status_exported_opened", name=saved_path.name))
            else:
                self.lbl_status.setText(tr("transcript.status_exported", name=saved_path.name))
        except Exception as e:
            self.lbl_status.setText(tr("transcript.status_export_error", error=e))

    def _open_docx_file(self) -> None:
        self._on_export_format("docx")

    def _open_containing_folder(self) -> None:
        target = self._current_docx_path
        if not target and self._exported_paths:
            target = next(iter(self._exported_paths.values()))
        if not target and self._current_track:
            target = self._current_track.file_path
        if not target and self._current_config and self._current_config.output_dir:
            target = self._current_config.output_dir

        if target:
            p = Path(target).resolve()
            if p.is_file():
                success = reveal_file_in_os(p)
                if not success and p.parent.exists():
                    open_path_in_os(p.parent)
            elif p.is_dir() and p.exists():
                open_path_in_os(p)
            elif p.parent.exists():
                open_path_in_os(p.parent)
            else:
                self.lbl_status.setText(tr("transcript.status_dir_not_found", path=p))
        else:
            self.lbl_status.setText(tr("transcript.status_no_folder"))

    def _copy_text(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(self.txt_display.toPlainText())
            self.lbl_status.setText(tr("transcript.status_copied"))

    # --- Synced audio playback & click-to-seek ---

    def _compute_slice_bounds_ms(self, track: AudioTrack) -> tuple[int, int]:
        total_sec = max(0.0, track.info.duration)
        cfg = track.slice_config
        if cfg.mode == SliceMode.FULL or cfg.is_full(total_sec):
            start_ms = 0
            end_ms = int(round(total_sec * 1000))
        else:
            start_ms = int(round(max(0.0, cfg.start_sec) * 1000))
            end_ms = int(round(cfg.effective_end(total_sec) * 1000))
        return start_ms, max(start_ms, end_ms)

    def refresh_playback_bounds(self) -> None:
        """Recalculate playback slider bounds after the active track's trim range changes."""
        if self._current_track is None:
            return
        self._slice_start_ms, self._slice_end_ms = self._compute_slice_bounds_ms(self._current_track)
        slice_dur_ms = max(0, self._slice_end_ms - self._slice_start_ms)
        self._playback_duration_ms = slice_dur_ms
        self._updating_slider = True
        try:
            self.slider_playback.setRange(0, max(1, slice_dur_ms))
            self.slider_playback.setValue(0)
        finally:
            self._updating_slider = False
        if self._player is not None:
            try:
                self._player.setPosition(self._slice_start_ms)
            except Exception:
                pass
        self._update_playback_time_label(0)

    def _load_track_audio(self, track: AudioTrack) -> None:
        self.release_player()
        self._loaded_audio_path = track.file_path
        self._slice_start_ms, self._slice_end_ms = self._compute_slice_bounds_ms(track)
        slice_dur_ms = max(0, self._slice_end_ms - self._slice_start_ms)
        self._playback_duration_ms = slice_dur_ms

        self.playback_bar.setVisible(True)
        self._updating_slider = True
        try:
            self.slider_playback.setRange(0, max(1, slice_dur_ms))
            self.slider_playback.setValue(0)
        finally:
            self._updating_slider = False
        self._update_playback_time_label(0)

        has_media = False
        if (
            QMediaPlayer is not None
            and QAudioOutput is not None
            and track.file_path.is_file()
            and track.file_path.stat().st_size > 0
        ):
            try:
                player = QMediaPlayer(self)
                audio_output = QAudioOutput(self)
                player.setAudioOutput(audio_output)
                player.positionChanged.connect(self._on_player_position_changed)
                player.durationChanged.connect(self._on_player_duration_changed)
                player.playbackStateChanged.connect(self._on_player_state_changed)
                if hasattr(player, "mediaStatusChanged"):
                    player.mediaStatusChanged.connect(self._on_media_status_changed)
                if hasattr(player, "errorOccurred"):
                    player.errorOccurred.connect(self._on_player_error)
                player.setSource(QUrl.fromLocalFile(str(track.file_path)))
                player.setPlaybackRate(self._PLAYBACK_RATES[self._playback_rate_idx])
                if self._slice_start_ms > 0:
                    player.setPosition(self._slice_start_ms)
                self._player = player
                self._audio_output = audio_output
                has_media = True
            except Exception:
                self._player = None
                self._audio_output = None

        self.btn_play_pause.setEnabled(has_media)
        self.slider_playback.setEnabled(has_media)
        self.btn_playback_speed.setEnabled(has_media)
        self.btn_play_pause.setToolTip(
            tr("transcript.play_tooltip") if has_media else tr("transcript.playback_unavailable")
        )
        self._update_play_pause_button()

    def _on_player_error(self, *_args) -> None:
        self._pending_seek_abs_ms = None
        self._pending_seek_deadline = 0.0
        self._update_play_pause_button()

    def _set_pending_seek(self, abs_ms: int) -> None:
        """Record an expected seek target with a brief settle deadline so stale frames are ignored."""
        self._pending_seek_abs_ms = abs_ms
        self._pending_seek_deadline = time.monotonic() + 0.5

    def _is_playing(self) -> bool:
        if self._player is None or QMediaPlayer is None:
            return False
        try:
            return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        except Exception:
            return False

    def _update_play_pause_button(self) -> None:
        if self._is_playing():
            self.btn_play_pause.setText(tr("transcript.pause"))
            self.btn_play_pause.setIcon(load_ui_icon("pause"))
        else:
            self.btn_play_pause.setText(tr("transcript.play"))
            self.btn_play_pause.setIcon(load_ui_icon("play"))

    def toggle_playback(self) -> None:
        """Toggle audio play/pause state."""
        if self._player is None or QMediaPlayer is None:
            return
        try:
            if self._is_playing():
                self._player.pause()
            else:
                if self._slice_end_ms > self._slice_start_ms and self._player.position() >= self._slice_end_ms:
                    self._player.setPosition(self._slice_start_ms)
                elif self._player.position() < self._slice_start_ms:
                    self._player.setPosition(self._slice_start_ms)
                self._player.play()
        except Exception:
            pass

    def pause_playback(self) -> None:
        """Pause playback if currently playing."""
        if self._player is not None and self._is_playing():
            try:
                self._player.pause()
            except Exception:
                pass

    def _cycle_playback_speed(self) -> None:
        self._playback_rate_idx = (self._playback_rate_idx + 1) % len(self._PLAYBACK_RATES)
        rate = self._PLAYBACK_RATES[self._playback_rate_idx]
        label = f"{rate:g}x"
        if "." not in label:
            label = f"{rate:.1f}x"
        self.btn_playback_speed.setText(label)
        if self._player is not None:
            try:
                self._player.setPlaybackRate(rate)
            except Exception:
                pass

    def _on_slider_pressed(self) -> None:
        self._slider_dragging = True

    def _on_slider_moved(self, rel_ms: int) -> None:
        self._update_playback_time_label(rel_ms)
        self._sync_segment_for_rel_ms(rel_ms, scroll=False)

    def _on_slider_released(self) -> None:
        self._slider_dragging = False
        self._seek_relative_ms(self.slider_playback.value())

    def _on_slider_value_changed(self, rel_ms: int) -> None:
        if self._updating_slider or self._slider_dragging:
            return
        self._seek_relative_ms(rel_ms)

    def _seek_relative_ms(self, rel_ms: int) -> None:
        clamped_rel = max(0, rel_ms)
        if self._playback_duration_ms > 0:
            clamped_rel = min(clamped_rel, self._playback_duration_ms)
        abs_ms = self._slice_start_ms + clamped_rel
        if self._player is not None:
            self._set_pending_seek(abs_ms)
            try:
                self._player.setPosition(abs_ms)
            except Exception:
                pass
        self._update_playback_time_label(clamped_rel)
        self._sync_segment_for_rel_ms(clamped_rel, scroll=False)
        self.playback_position_changed.emit(clamped_rel / 1000.0)

    def seek_to_segment(self, index: int, autoplay: bool = True) -> None:
        """Seek audio playback to the start of transcript segment `index` and highlight it."""
        if not (0 <= index < len(self._raw_segments)):
            return
        seg = self._raw_segments[index]
        rel_ms = int(round(max(0.0, seg.start) * 1000))
        if self._playback_duration_ms > 0:
            rel_ms = min(rel_ms, self._playback_duration_ms)
        abs_ms = self._slice_start_ms + rel_ms

        self._active_segment_idx = index
        self._highlight_active_segment(scroll=True)
        self.segment_activated.emit(index)

        self._updating_slider = True
        try:
            if rel_ms > self.slider_playback.maximum():
                self.slider_playback.setMaximum(rel_ms)
            self.slider_playback.setValue(rel_ms)
        finally:
            self._updating_slider = False
        self._update_playback_time_label(rel_ms)
        self.playback_position_changed.emit(rel_ms / 1000.0)

        if self._player is not None:
            self._set_pending_seek(abs_ms)
            try:
                self._player.setPosition(abs_ms)
                if autoplay:
                    self._player.play()
            except Exception:
                pass

    def _on_media_status_changed(self, status: object) -> None:
        if (
            self._pending_seek_abs_ms is not None
            and self._player is not None
            and QMediaPlayer is not None
            and status
            in (
                QMediaPlayer.MediaStatus.LoadedMedia,
                QMediaPlayer.MediaStatus.BufferedMedia,
            )
        ):
            target = self._pending_seek_abs_ms
            self._set_pending_seek(target)
            try:
                self._player.setPosition(target)
            except Exception:
                pass

    def _on_player_duration_changed(self, duration_ms: int) -> None:
        if duration_ms <= 0:
            return
        if self._current_track is not None:
            cfg = self._current_track.slice_config
            if cfg.mode == SliceMode.FULL or cfg.is_full(self._current_track.info.duration):
                self._slice_start_ms = 0
                self._slice_end_ms = duration_ms
        slice_dur_ms = max(0, self._slice_end_ms - self._slice_start_ms)
        if slice_dur_ms <= 0:
            slice_dur_ms = duration_ms
        self._playback_duration_ms = slice_dur_ms
        self._updating_slider = True
        try:
            self.slider_playback.setRange(0, max(1, slice_dur_ms))
        finally:
            self._updating_slider = False
        if self._pending_seek_abs_ms is not None:
            rel_ms = max(0, self._pending_seek_abs_ms - self._slice_start_ms)
        elif self._player is not None:
            rel_ms = max(0, self._player.position() - self._slice_start_ms)
        else:
            rel_ms = 0
        self._update_playback_time_label(rel_ms)

    def _on_player_position_changed(self, abs_ms: int) -> None:
        if self._pending_seek_abs_ms is not None:
            # Drop only asynchronous pre-seek backend ticks within the settle window
            if self.sender() is self._player and time.monotonic() <= self._pending_seek_deadline:
                if abs(abs_ms - self._pending_seek_abs_ms) > 250:
                    return
            self._pending_seek_abs_ms = None
            self._pending_seek_deadline = 0.0

        if self._slice_end_ms > self._slice_start_ms and abs_ms >= self._slice_end_ms:
            rel_ms = self._slice_end_ms - self._slice_start_ms
            if self._is_playing():
                self.pause_playback()
        else:
            rel_ms = max(0, abs_ms - self._slice_start_ms)

        if not self._slider_dragging:
            self._updating_slider = True
            try:
                self.slider_playback.setValue(min(rel_ms, self.slider_playback.maximum()))
            finally:
                self._updating_slider = False
            self._update_playback_time_label(rel_ms)

        self._sync_segment_for_rel_ms(rel_ms, scroll=self._is_playing())
        self.playback_position_changed.emit(rel_ms / 1000.0)

    def _on_player_state_changed(self, _state: object) -> None:
        self._update_play_pause_button()

    def _update_playback_time_label(self, rel_ms: int) -> None:
        cur_str = format_seconds(max(0, rel_ms) / 1000.0)
        tot_str = format_seconds(max(0, self._playback_duration_ms) / 1000.0)
        self.lbl_playback_time.setText(f"{cur_str} / {tot_str}")

    def _find_segment_for_time(self, rel_sec: float) -> int | None:
        if not self._raw_segments or self._raw_segments_stale:
            return None
        matched: int | None = None
        for idx, seg in enumerate(self._raw_segments):
            if seg.start <= rel_sec <= seg.end:
                matched = idx
        return matched

    def _sync_segment_for_rel_ms(self, rel_ms: int, scroll: bool = False) -> None:
        idx = self._find_segment_for_time(max(0, rel_ms) / 1000.0)
        if idx != self._active_segment_idx:
            self._active_segment_idx = idx
            self._highlight_active_segment(scroll=scroll)
            if idx is not None:
                self.segment_activated.emit(idx)

    def _highlight_active_segment(self, scroll: bool = False) -> None:
        if (
            self._active_mode != "raw"
            or self._raw_segments_stale
            or self._active_segment_idx is None
            or not (0 <= self._active_segment_idx < len(self._raw_segments))
        ):
            self.txt_display.setExtraSelections([])
            return

        seg = self._raw_segments[self._active_segment_idx]
        doc = self.txt_display.document()
        block = doc.findBlockByNumber(self._active_segment_idx)
        if not block.isValid() or not block.text().startswith(seg.formatted_timerange):
            # Fallback scan if user inserted blank lines
            block = doc.begin()
            found_block = None
            while block.isValid():
                if block.text().startswith(seg.formatted_timerange):
                    found_block = block
                    break
                block = block.next()
            if found_block is None:
                self.txt_display.setExtraSelections([])
                return
            block = found_block

        p = get_palette()
        bg = QColor(p.primary)
        bg.setAlpha(28)

        sel = QTextEdit.ExtraSelection()
        sel_cursor = QTextCursor(block)
        sel_cursor.movePosition(QTextCursor.StartOfBlock)
        sel_cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        sel.cursor = sel_cursor
        sel.format.setBackground(bg)
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        self.txt_display.setExtraSelections([sel])

        if scroll:
            scroll_cursor = QTextCursor(block)
            vp_rect = self.txt_display.viewport().rect()
            block_rect = self.txt_display.cursorRect(scroll_cursor)
            if not vp_rect.contains(block_rect):
                cur = self.txt_display.textCursor()
                self._updating_text = True
                try:
                    self.txt_display.setTextCursor(scroll_cursor)
                    self.txt_display.ensureCursorVisible()
                finally:
                    self.txt_display.setTextCursor(cur)
                    self._updating_text = False

    def _segment_index_at_pos(self, pos: QPoint, require_timestamp: bool) -> int | None:
        if self._active_mode != "raw" or self._raw_segments_stale:
            return None
        cursor = self.txt_display.cursorForPosition(pos)
        block_num = cursor.blockNumber()
        if not (0 <= block_num < len(self._raw_segments)):
            return None
        if not require_timestamp:
            return block_num
        seg = self._raw_segments[block_num]
        if cursor.positionInBlock() <= len(seg.formatted_timerange):
            return block_num
        return None

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.txt_display.viewport():
            etype = event.type()
            if etype == QEvent.MouseMove and self._active_mode == "raw":
                pos = event.position().toPoint()
                ctrl_cmd = bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
                idx = self._segment_index_at_pos(pos, require_timestamp=not ctrl_cmd)
                self.txt_display.viewport().setCursor(
                    Qt.PointingHandCursor if idx is not None else Qt.IBeamCursor
                )
            elif etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                ctrl_cmd = bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
                self._pressed_seek_block = self._segment_index_at_pos(
                    pos, require_timestamp=not ctrl_cmd
                )
            elif etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                pressed_block = self._pressed_seek_block
                self._pressed_seek_block = None
                if self._active_mode == "raw" and not self.txt_display.textCursor().hasSelection():
                    pos = event.position().toPoint()
                    ctrl_cmd = bool(event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier))
                    idx = self._segment_index_at_pos(pos, require_timestamp=not ctrl_cmd)
                    if idx is not None and idx == pressed_block:
                        self.seek_to_segment(idx, autoplay=True)
                        return True
        return super().eventFilter(watched, event)

    def release_player(self) -> None:
        """Stop and release QMediaPlayer and QAudioOutput cleanly."""
        self._loaded_audio_path = None
        self._pending_seek_abs_ms = None
        self._pending_seek_deadline = 0.0
        if self._player is not None:
            try:
                self._player.blockSignals(True)
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass
            self._player.deleteLater()
            self._player = None
        if self._audio_output is not None:
            self._audio_output.blockSignals(True)
            self._audio_output.deleteLater()
            self._audio_output = None

    def closeEvent(self, event) -> None:
        self.release_player()
        super().closeEvent(event)
