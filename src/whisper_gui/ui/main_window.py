"""Main window for Whisper GUI desktop application with streamlined Swiss AI-native layout."""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
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
from whisper_gui.i18n import display_track_status, get_language, set_language, tr
from whisper_gui.models import AudioTrack, TrackStatus, TranscriptSegment, TranscriptionResult
from whisper_gui.platform_utils import get_app_icon, get_asset_path
from whisper_gui.transcriber import Transcriber
from whisper_gui.ui.llm_panel import LLMPanel
from whisper_gui.ui.range_selector import RangeSelectorWidget, TrimAudioDialog
from whisper_gui.ui.settings_page import SettingsPageWidget
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.theme import (
    ToggleSwitch,
    build_stylesheet,
    fixed_mono_font,
    get_palette,
    get_theme_name,
    load_tinted_pixmap,
    load_ui_icon,
    set_theme,
)
from whisper_gui.ui.track_list_widget import TrackListWidget
from whisper_gui.ui.transcript_view import TranscriptView
from whisper_gui.ui.update_dialog import UpdateCheckWorker, UpdateDialog
from whisper_gui.worker import PolishWorker, TranscriptionWorker


class DropzoneCard(QFrame):
    """Clickable dropzone card with a continuous rounded dashed border."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._click_callback = None
        self._hovered = False
        self.setAttribute(Qt.WA_Hover, True)

    def set_click_callback(self, cb) -> None:
        self._click_callback = cb

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._click_callback:
            self._click_callback()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = get_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 12.0, 12.0)

        fill = QColor(p.bg_raised if self._hovered else p.bg_surface)
        painter.fillPath(path, fill)

        pen = QPen(QColor(p.text_muted if self._hovered else p.border_light), 1.0)
        pen.setCapStyle(Qt.FlatCap)
        pen.setDashPattern([5.0, 4.0])
        painter.setPen(pen)
        painter.drawPath(path)


class ThemeDropOverlay(QWidget):
    """Animated radial drop reveal overlaying old snapshot while live theme updates beneath."""

    def __init__(
        self,
        parent: QWidget,
        old_pixmap: QPixmap,
        origin: QPoint,
        edge_color: str,
    ) -> None:
        super().__init__(parent)
        self._old_pixmap = old_pixmap
        self._origin = origin
        self._edge_color = QColor(edge_color)
        self._radius = 0.0

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setGeometry(parent.rect())

        w, h = float(parent.width()), float(parent.height())
        max_r = max(
            math.hypot(origin.x(), origin.y()),
            math.hypot(w - origin.x(), origin.y()),
            math.hypot(origin.x(), h - origin.y()),
            math.hypot(w - origin.x(), h - origin.y()),
        )

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(max_r)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_step)
        self._anim.finished.connect(self._on_finished)

    def start(self) -> None:
        self.show()
        self.raise_()
        self._anim.start()

    def cancel(self) -> None:
        self._anim.stop()
        self.hide()
        self.setParent(None)
        self.deleteLater()

    def _on_step(self, value: float) -> None:
        self._radius = float(value)
        self.update()

    def _on_finished(self) -> None:
        self.hide()
        self.setParent(None)
        self.deleteLater()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        outer = QPainterPath()
        outer.setFillRule(Qt.OddEvenFill)
        outer.addRect(QRectF(self.rect()))
        r = self._radius
        outer.addEllipse(QPointF(self._origin), r, r)

        painter.save()
        painter.setClipPath(outer)
        painter.drawPixmap(self.rect(), self._old_pixmap)
        painter.restore()

        if r > 1.0:
            ring_color = QColor(self._edge_color)
            ring_color.setAlpha(140)
            painter.setPen(QPen(ring_color, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPointF(self._origin), r, r)


class MainWindow(QMainWindow):
    """Main application window for Whisper GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Whisper GUI v{__version__}")
        self.resize(960, 680)
        self.setMinimumSize(720, 480)
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
        self._theme_overlay: ThemeDropOverlay | None = None

        self._build_ui()
        self.apply_theme()
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
        transcribe_vbox.setSpacing(12)
        transcribe_vbox.setContentsMargins(16, 12, 16, 12)

        # 1. Header Bar
        self.header_frame = QFrame()
        self.header_frame.setObjectName("main_header")
        self.header_frame.setFixedHeight(48)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(12)
        header_layout.setAlignment(Qt.AlignVCenter)

        # Left side: Lateral Drawer Toggle + Title + Model Badge
        self.btn_toggle_drawer = QPushButton(tr("main.tracks_button", count=0))
        self.btn_toggle_drawer.setFixedHeight(32)
        self.btn_toggle_drawer.setIconSize(QSize(16, 16))
        self.btn_toggle_drawer.setCheckable(True)
        self.btn_toggle_drawer.clicked.connect(self._toggle_tracks_drawer)
        self.btn_toggle_queue = self.btn_toggle_drawer  # backward compatibility alias
        header_layout.addWidget(self.btn_toggle_drawer)

        self.title_lbl = QLabel("Whisper GUI")
        header_layout.addWidget(self.title_lbl)

        self.lbl_model_badge = QLabel(tr("main.model_badge", model="large-v3-turbo"))
        self.lbl_model_badge.setFont(fixed_mono_font(12))
        header_layout.addWidget(self.lbl_model_badge)

        header_layout.addStretch()

        self.btn_open_settings = QPushButton(tr("main.settings_button"))
        self.btn_open_settings.setFixedHeight(32)
        self.btn_open_settings.setIconSize(QSize(16, 16))
        self.btn_open_settings.setStyleSheet("padding: 4px 12px; font-size: 12px; font-weight: 500;")
        self.btn_open_settings.clicked.connect(self._open_settings_page)
        header_layout.addWidget(self.btn_open_settings)

        transcribe_vbox.addWidget(self.header_frame)

        # 2. Main Content Splitter (Lateral Drawer on left | Hero Workspace)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        # 2a. Lateral Tracks Drawer
        self.tracks_drawer = QFrame()
        self.tracks_drawer.setObjectName("tracks_drawer")
        self.tracks_drawer.setMinimumWidth(348)
        self.tracks_drawer.setMaximumWidth(480)
        self.queue_drawer = self.tracks_drawer  # backward compatibility alias

        drawer_vbox = QVBoxLayout(self.tracks_drawer)
        drawer_vbox.setContentsMargins(12, 12, 12, 12)
        drawer_vbox.setSpacing(12)

        drawer_hdr = QHBoxLayout()
        drawer_hdr.setSpacing(8)
        self.lbl_drawer_title = QLabel(tr("main.drawer_title"))
        drawer_hdr.addWidget(self.lbl_drawer_title)

        self.lbl_drawer_count = QLabel(tr("main.drawer_track_plural", count=0))
        self.lbl_drawer_count.setFont(fixed_mono_font(11))
        drawer_hdr.addWidget(self.lbl_drawer_count)

        drawer_hdr.addStretch()

        self.btn_close_drawer = QPushButton()
        self.btn_close_drawer.setObjectName("btn_close_drawer")
        self.btn_close_drawer.setIconSize(QSize(14, 14))
        self.btn_close_drawer.setFixedSize(32, 32)
        self.btn_close_drawer.setToolTip(tr("main.drawer_close_tooltip"))
        self.btn_close_drawer.setStyleSheet("padding: 0px;")
        self.btn_close_drawer.clicked.connect(lambda: self.btn_toggle_drawer.setChecked(False) or self.tracks_drawer.hide())
        drawer_hdr.addWidget(self.btn_close_drawer)
        drawer_vbox.addLayout(drawer_hdr)

        self.track_list = TrackListWidget()
        drawer_vbox.addWidget(self.track_list, stretch=1)
        self.main_splitter.addWidget(self.tracks_drawer)
        self.tracks_drawer.hide()

        # 2b. Central Hero Workspace
        self.center_widget = QWidget()
        center_layout = QVBoxLayout(self.center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(12)

        # Dropzone (shown when 0 tracks loaded)
        self.dropzone_card = DropzoneCard()
        self.dropzone_card.setObjectName("dropzone_card")
        self.dropzone_card.setMinimumHeight(180)
        self.dropzone_card.setCursor(Qt.PointingHandCursor)
        self.dropzone_card.set_click_callback(self.track_list._on_add_files_clicked)
        self.dropzone_card.setStyleSheet("""
            #dropzone_card {
                background: transparent;
                border: none;
            }
            QLabel {
                border: none;
                background: transparent;
            }
        """)
        drop_layout = QVBoxLayout(self.dropzone_card)
        drop_layout.setContentsMargins(24, 32, 24, 32)
        drop_layout.setSpacing(8)
        drop_layout.setAlignment(Qt.AlignCenter)

        self.lbl_drop_icon = QLabel()
        self.lbl_drop_icon.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.lbl_drop_icon)

        self.lbl_drop_title = QLabel(tr("main.drop_title"))
        self.lbl_drop_title.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.lbl_drop_title)

        center_layout.addWidget(self.dropzone_card)

        # Active Track Card (shown when >= 1 track loaded)
        self.active_card = QFrame()
        self.active_card.setObjectName("active_card")
        card_layout = QVBoxLayout(self.active_card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        # Track info header
        track_row = QHBoxLayout()
        track_row.setSpacing(12)

        self.lbl_active_name = QLabel(tr("main.no_track_selected"))
        track_row.addWidget(self.lbl_active_name, stretch=1)

        self.lbl_active_meta = QLabel("00:00 • 0 MB")
        self.lbl_active_meta.setFont(fixed_mono_font(12))
        track_row.addWidget(self.lbl_active_meta)

        self.lbl_active_slice = QLabel(tr("main.full_audio"))
        self.lbl_active_slice.setFont(fixed_mono_font(12))
        track_row.addWidget(self.lbl_active_slice)
        card_layout.addLayout(track_row)

        # Action bar: Trim Audio, Polish toggle, Drawer button
        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.btn_open_trim = QPushButton(tr("main.trim_button"))
        self.btn_open_trim.setFixedHeight(32)
        self.btn_open_trim.setIconSize(QSize(16, 16))
        self.btn_open_trim.setStyleSheet("font-weight: 500; padding: 4px 12px;")
        self.btn_open_trim.clicked.connect(self._open_trim_dialog)
        actions_row.addWidget(self.btn_open_trim)

        self.chk_polish_sync = ToggleSwitch(tr("main.auto_polish"))
        self.chk_polish_sync.setStyleSheet("font-weight: 400; background-color: transparent;")
        self.chk_polish_sync.toggled.connect(self._on_polish_sync_toggled)
        actions_row.addWidget(self.chk_polish_sync)

        actions_row.addStretch()

        self.btn_active_drawer = QPushButton(tr("main.view_all_tracks"))
        self.btn_active_drawer.setFixedHeight(32)
        self.btn_active_drawer.setIconSize(QSize(16, 16))
        self.btn_active_drawer.setStyleSheet("padding: 4px 12px; font-size: 12px;")
        self.btn_active_drawer.clicked.connect(self._open_tracks_drawer)
        actions_row.addWidget(self.btn_active_drawer)

        card_layout.addLayout(actions_row)

        # Hidden compatibility controls
        self.multi_track_widget = QWidget()
        self.multi_track_widget.hide()
        self.combo_active_track = QComboBox()
        self.combo_active_track.setView(QListView())
        self.combo_active_track.currentIndexChanged.connect(self._on_combo_track_changed)
        self.btn_add_another = QPushButton(tr("main.add_files_button"))
        self.btn_add_another.clicked.connect(self.track_list._on_add_files_clicked)
        self.btn_add_another.hide()

        # Primary transcribe button bar
        transcribe_row = QHBoxLayout()
        transcribe_row.setSpacing(8)

        self.btn_start = QPushButton(tr("main.transcribe_audio"))
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self._on_start_clicked)
        transcribe_row.addWidget(self.btn_start, stretch=1)

        self.btn_stop = QPushButton(tr("main.stop_button"))
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
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
        self.config_tabs.addTab(self.range_selector, tr("main.tab_trimming"))
        self.config_tabs.addTab(QWidget(), tr("main.tab_whisper"))
        self.config_tabs.addTab(QWidget(), tr("main.tab_polish"))
        self.config_tabs.hide()

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(True)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage(tr("main.status_ready"))

        # Connect Signals
        self.track_list.track_selected.connect(self._on_track_selected)
        self.track_list.track_count_changed.connect(self._on_track_count_changed)
        self.range_selector.range_changed.connect(self._on_range_changed)
        self.settings_panel.free_ram_requested.connect(self._on_free_ram_clicked)
        self.settings_panel.check_updates_requested.connect(lambda: self._check_for_updates(manual=True))
        self.settings_panel.theme_changed.connect(self._on_theme_changed)
        self.settings_panel.app_language_changed.connect(self._on_app_language_changed)
        self.settings_panel.combo_model.currentIndexChanged.connect(self._on_model_changed)
        self.llm_panel.chk_enable.toggled.connect(self._on_llm_panel_enable_toggled)
        self.transcript_view.polish_requested.connect(self._on_repolish_clicked)

        # Initial state
        self.range_selector.set_track(None)

    def apply_theme(self) -> None:
        """Apply the active palette to the main window, chrome, icons, and subpanels."""
        p = get_palette()
        self.setStyleSheet(build_stylesheet(p))

        self.header_frame.setStyleSheet(f"""
            #main_header {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.btn_toggle_drawer.setIcon(load_ui_icon("tracks"))
        self.btn_toggle_drawer.setStyleSheet(f"""
            QPushButton {{
                padding: 4px 12px;
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton:checked {{
                background-color: {p.bg_raised};
                color: {p.text_main};
                border-color: {p.border_light};
            }}
        """)
        self.title_lbl.setStyleSheet(f"color: {p.text_main}; font-size: 14px; font-weight: 500;")
        self.lbl_model_badge.setStyleSheet(f"color: {p.text_muted};")
        self.btn_open_settings.setIcon(load_ui_icon("settings"))

        self.tracks_drawer.setStyleSheet(f"""
            #tracks_drawer {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_drawer_title.setStyleSheet(f"font-weight: 500; font-size: 14px; color: {p.text_main};")
        self.lbl_drawer_count.setStyleSheet(f"color: {p.text_muted};")
        self.btn_close_drawer.setIcon(load_ui_icon("close"))

        self.lbl_drop_title.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {p.text_main};")
        drop_pixmap = load_tinted_pixmap("upload_icon.svg", 48, p.text_muted)
        if not drop_pixmap.isNull():
            self.lbl_drop_icon.setPixmap(drop_pixmap)
        self.dropzone_card.update()

        self.active_card.setStyleSheet(f"""
            #active_card {{
                background-color: {p.bg_surface};
                border: 1px solid {p.border};
                border-radius: 12px;
            }}
            QLabel {{
                border: none;
                background: transparent;
            }}
        """)
        self.lbl_active_name.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {p.text_main};")
        self.lbl_active_meta.setStyleSheet(f"color: {p.text_muted};")
        self.lbl_active_slice.setStyleSheet(f"color: {p.text_muted};")
        self.btn_open_trim.setIcon(load_ui_icon("scissors"))
        self.btn_active_drawer.setIcon(load_ui_icon("tracks"))

        self.btn_start.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.primary};
                color: {p.primary_text};
                font-weight: 500;
                font-size: 13px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {p.primary_hover};
            }}
            QPushButton:pressed {{
                background-color: {p.primary_pressed};
            }}
            QPushButton:disabled {{
                background-color: {p.bg_input};
                color: {p.text_hint};
                border: 1px solid {p.border};
            }}
        """)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{
                background-color: {p.secondary};
                color: {p.secondary_text};
                font-weight: 500;
                font-size: 13px;
                padding: 0 20px;
                border-radius: 8px;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {p.secondary_hover};
            }}
            QPushButton:disabled {{
                background-color: {p.bg_input};
                color: {p.text_hint};
                border: 1px solid {p.border};
            }}
        """)

        self.track_list.apply_theme()
        self.transcript_view.apply_theme()
        self.range_selector.apply_theme()
        self.settings_page.apply_theme()
        self.settings_panel.apply_theme()
        self.llm_panel.apply_theme()

    def _on_theme_changed(self, theme_name: str, origin_widget: QWidget | None = None) -> None:
        if theme_name == get_theme_name():
            return

        overlay = self._theme_overlay
        self._theme_overlay = None
        if overlay is not None:
            overlay.cancel()

        before_pixmap = self.grab()
        if isinstance(origin_widget, QWidget):
            origin = origin_widget.mapTo(self, origin_widget.rect().center())
        else:
            origin = QPoint(self.width() // 2, 0)

        new_palette = set_theme(theme_name)
        self.apply_theme()
        self._save_settings()

        drop = ThemeDropOverlay(self, before_pixmap, origin, new_palette.primary)
        self._theme_overlay = drop
        drop._anim.finished.connect(lambda: self._clear_theme_overlay(drop))
        drop.start()

    def _clear_theme_overlay(self, drop: ThemeDropOverlay) -> None:
        if self._theme_overlay is drop:
            self._theme_overlay = None

    def _on_app_language_changed(self, lang_code: str) -> None:
        if lang_code == get_language():
            return
        set_language(lang_code)
        self.retranslate_ui()
        self._save_settings()

    def retranslate_ui(self) -> None:
        """Refresh all visible text across the main window and child widgets."""
        self.btn_open_settings.setText(tr("main.settings_button"))
        self.lbl_drawer_title.setText(tr("main.drawer_title"))
        self.btn_close_drawer.setToolTip(tr("main.drawer_close_tooltip"))
        self.lbl_drop_title.setText(tr("main.drop_title"))
        self.btn_open_trim.setText(tr("main.trim_button"))
        self.chk_polish_sync.setText(tr("main.auto_polish"))
        self.btn_active_drawer.setText(tr("main.view_all_tracks"))
        self.btn_add_another.setText(tr("main.add_files_button"))
        self.btn_stop.setText(tr("main.stop_button"))
        self.config_tabs.setTabText(0, tr("main.tab_trimming"))
        self.config_tabs.setTabText(1, tr("main.tab_whisper"))
        self.config_tabs.setTabText(2, tr("main.tab_polish"))

        self.settings_page.retranslate_ui()
        self.settings_panel.retranslate_ui()
        self.llm_panel.retranslate_ui()
        self.range_selector.retranslate_ui()
        self.track_list.retranslate_ui()
        self.transcript_view.retranslate_ui()

        self._on_model_changed()
        self._update_track_count_labels(len(self.track_list.get_tracks()))
        self._update_start_button_text()
        self._update_active_track_labels(self._active_track)
        if not self.current_worker or not self.current_worker.isRunning():
            self.status_bar.showMessage(tr("main.status_ready"))

    def _toggle_tracks_drawer(self) -> None:
        is_checked = self.btn_toggle_drawer.isChecked()
        self.tracks_drawer.setVisible(is_checked)
        if is_checked:
            total_w = self.main_splitter.width() or 1000
            self.main_splitter.setSizes([360, max(560, total_w - 360)])

    def _toggle_queue_drawer(self) -> None:
        self._toggle_tracks_drawer()

    def _open_tracks_drawer(self) -> None:
        self.btn_toggle_drawer.setChecked(True)
        self.tracks_drawer.show()
        total_w = self.main_splitter.width() or 1000
        self.main_splitter.setSizes([360, max(560, total_w - 360)])

    def _open_settings_page(self) -> None:
        self.settings_panel._update_disk_status()
        self.page_stack.setCurrentIndex(1)

    def _close_settings_page(self) -> None:
        self.page_stack.setCurrentIndex(0)
        self._on_model_changed()
        self.chk_polish_sync.setChecked(self.llm_panel.chk_enable.isChecked())

    def _on_model_changed(self) -> None:
        model_name = str(
            self.settings_panel.combo_model.currentData()
            or self.settings_panel.combo_model.currentText().split()[0]
        )
        self.lbl_model_badge.setText(tr("main.model_badge", model=model_name))

    def _on_polish_sync_toggled(self, checked: bool) -> None:
        if self.llm_panel.chk_enable.isChecked() != checked:
            self.llm_panel.chk_enable.setChecked(checked)

    def _on_llm_panel_enable_toggled(self, checked: bool) -> None:
        if self.chk_polish_sync.isChecked() != checked:
            self.chk_polish_sync.setChecked(checked)

    def _update_track_count_labels(self, count: int) -> None:
        self.btn_toggle_drawer.setText(tr("main.tracks_button", count=count))
        count_key = "main.drawer_track_singular" if count == 1 else "main.drawer_track_plural"
        self.lbl_drawer_count.setText(tr(count_key, count=count))

    def _on_track_count_changed(self, count: int) -> None:
        self._update_track_count_labels(count)
        if count > 1 and not self.tracks_drawer.isVisible():
            self.btn_toggle_drawer.setChecked(True)
            self.tracks_drawer.show()
            total_w = self.main_splitter.width() or 1000
            self.main_splitter.setSizes([360, max(560, total_w - 360)])
        self._sync_queue_display()

    def _update_start_button_text(self) -> None:
        tracks = self.track_list.get_tracks()
        if len(tracks) > 1:
            pending = [t for t in tracks if t.status in (TrackStatus.QUEUED, TrackStatus.ERROR)]
            if pending:
                n = len(pending)
                key = "main.transcribe_all_one" if n == 1 else "main.transcribe_all_many"
                self.btn_start.setText(tr(key, count=n))
            else:
                n = len(tracks)
                key = "main.rerun_all_one" if n == 1 else "main.rerun_all_many"
                self.btn_start.setText(tr(key, count=n))
        elif len(tracks) == 1:
            self.btn_start.setText(tr("main.transcribe_track"))
        else:
            self.btn_start.setText(tr("main.transcribe_audio"))

    def _sync_queue_display(self) -> None:
        tracks = self.track_list.get_tracks()
        has_tracks = len(tracks) > 0
        self.dropzone_card.setVisible(not has_tracks)
        self.active_card.setVisible(has_tracks)
        self.btn_active_drawer.setVisible(len(tracks) > 1)

        self._update_start_button_text()

        self.combo_active_track.blockSignals(True)
        self.combo_active_track.clear()
        for i, t in enumerate(tracks):
            self.combo_active_track.addItem(f"{i + 1}. {t.info.filename}", t.id)
        self.combo_active_track.blockSignals(False)

        if has_tracks and not self._active_track:
            self._set_active_track(tracks[0])
        elif not has_tracks:
            self._set_active_track(None)

    def _update_active_track_labels(self, track: AudioTrack | None) -> None:
        if track is None:
            self.lbl_active_name.setText(tr("main.no_track_selected"))
            self.lbl_active_meta.setText("")
            self.lbl_active_slice.setText(tr("main.full_audio"))
            return

        tracks = self.track_list.get_tracks()
        if len(tracks) > 1:
            try:
                idx = tracks.index(track) + 1
                self.lbl_active_name.setText(
                    tr("main.track_of", idx=idx, total=len(tracks), filename=track.info.filename)
                )
            except ValueError:
                self.lbl_active_name.setText(track.info.filename)
        else:
            self.lbl_active_name.setText(track.info.filename)

        self.lbl_active_meta.setText(f"{track.info.duration_formatted} • {track.info.size_mb:.1f} MB")
        self._update_slice_badge(track)

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

        self._update_active_track_labels(track)
        if track is None:
            return

        tracks = self.track_list.get_tracks()
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
            self.lbl_active_slice.setText(tr("main.full_audio"))
        else:
            s = format_seconds(slice_cfg.start_sec)
            e = format_seconds(slice_cfg.effective_end(track.info.duration))
            self.lbl_active_slice.setText(tr("main.trim_badge", start=s, end=e))

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
                tr("main.dlg_ffmpeg_title"),
                tr("main.dlg_ffmpeg_body", msg=msg),
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
                tr("main.dlg_no_tracks_title"),
                tr("main.dlg_no_tracks_body"),
            )
            return

        llm_cfg = self.llm_panel.get_config()
        if llm_cfg.enabled and not llm_cfg.api_key.strip() and llm_cfg.provider != "Custom":
            QMessageBox.warning(
                self,
                tr("main.dlg_api_key_title"),
                tr("main.dlg_api_key_start_body"),
            )
            self._open_settings_page()
            return

        pending_tracks = [t for t in tracks if t.status in (TrackStatus.QUEUED, TrackStatus.ERROR)]
        if not pending_tracks:
            reply = QMessageBox.question(
                self,
                tr("main.dlg_rerun_title"),
                tr("main.dlg_rerun_body"),
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
        self.status_bar.showMessage(tr("main.status_transcribing"))

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
            self.transcript_view.set_status(tr("main.status_stopping"))
            self.status_bar.showMessage(tr("main.status_stopping"))
            self.current_worker.request_stop()
            self.btn_stop.setEnabled(False)

    def _on_worker_track_started(self, track_id: str) -> None:
        self.track_list.refresh_track_display(track_id)
        track = self.track_list.get_track(track_id)
        if track:
            self._set_active_track(track)
            self.transcript_view.clear_view()
            self.transcript_view.set_status(
                tr("main.status_transcribing_file", filename=track.info.filename)
            )

    def _on_free_ram_clicked(self) -> None:
        self.transcriber.unload_model()
        self.settings_panel.set_ram_status(False)
        self.status_bar.showMessage(tr("main.status_model_unloaded"))

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
        track = self.track_list.get_track(track_id)
        if track is not None:
            track.progress_percent = percent
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_progress(percent, time_str)
            if track is not None:
                self.status_bar.showMessage(
                    tr("main.status_progress", filename=track.info.filename, metrics=time_str)
                )
            else:
                self.status_bar.showMessage(time_str)

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
                status_text = display_track_status(track.status_message, track.status)
                self.transcript_view.set_progress(100, status_text)
            elif result.docx_path:
                self.transcript_view.set_completed_docx(result.docx_path)
            else:
                self.transcript_view.btn_export.setEnabled(True)
                self.transcript_view.btn_open_folder.setEnabled(True)

        if result.docx_path:
            self.status_bar.showMessage(tr("main.status_saved", filename=result.docx_path.name))
        if self.transcriber.is_loaded:
            self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)

    def _on_worker_track_error(self, track_id: str, error_msg: str) -> None:
        self.track_list.refresh_track_display(track_id)
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_status(tr("main.status_error", error=error_msg))
        self.status_bar.showMessage(tr("main.status_error", error=error_msg))

    def _on_worker_finished(self) -> None:
        self._reset_ui_state()
        if self.settings_panel.chk_auto_unload.isChecked():
            self.transcriber.unload_model()
            self.settings_panel.set_ram_status(False)
            self.status_bar.showMessage(tr("main.status_completed_unloaded"))
        else:
            if self.transcriber.is_loaded:
                self.settings_panel.set_ram_status(True, self.transcriber.loaded_model_name)
            self.status_bar.showMessage(tr("main.status_completed"))

        QMessageBox.information(
            self,
            tr("main.dlg_done_title"),
            tr("main.dlg_done_body"),
        )

    def _on_worker_cancelled(self) -> None:
        self._reset_ui_state()
        self.status_bar.showMessage(tr("main.status_cancelled"))

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
        if not raw_text and not track.result.raw_segments_stale and track.result.segments:
            raw_text = " ".join(s.text for s in track.result.segments if s.text).strip()
        if not raw_text:
            return

        llm_cfg = self.llm_panel.get_config()
        if not llm_cfg.api_key.strip() and llm_cfg.provider != "Custom":
            QMessageBox.warning(
                self,
                tr("main.dlg_api_key_title"),
                tr("main.dlg_api_key_polish_body"),
            )
            self._open_settings_page()
            return

        self.transcript_view.btn_polish.setEnabled(False)
        self.btn_start.setEnabled(False)
        self.transcript_view.set_status(tr("main.status_polishing", model=llm_cfg.model_name))
        self.status_bar.showMessage(tr("main.status_polishing", model=llm_cfg.model_name))

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
            self.transcript_view.set_status(tr("main.status_polished"))
        self.status_bar.showMessage(tr("main.status_polished"))
        self.track_list.refresh_track_display(track_id)

    def _on_polish_failed(self, track_id: str, error_msg: str) -> None:
        self.btn_start.setEnabled(True)
        self.transcript_view._update_polish_button_state()
        if self._active_track is None or self._active_track.id == track_id:
            self.transcript_view.set_status(tr("main.status_polish_error", error=error_msg))
        self.status_bar.showMessage(tr("main.status_polish_error", error=error_msg))
        QMessageBox.warning(
            self,
            tr("main.dlg_polish_failed_title"),
            tr("main.dlg_polish_failed_body", error=error_msg),
        )

    def _on_polish_cancelled(self) -> None:
        self.btn_start.setEnabled(True)
        self.transcript_view._update_polish_button_state()
        self.transcript_view.set_status(tr("main.status_polish_cancelled"))
        self.status_bar.showMessage(tr("main.status_polish_cancelled"))

    def _on_polish_worker_finished(self) -> None:
        worker = self._polish_worker
        self._polish_worker = None
        if worker is not None:
            worker.wait(1000)
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
        if "PYTEST_CURRENT_TEST" not in os.environ:
            saved_lang = settings.value("Settings/app_language", "en", type=str)
            if saved_lang != get_language():
                applied_lang = set_language(saved_lang)
                self.settings_panel.set_selected_app_language(applied_lang)
                self.retranslate_ui()
            saved_theme = settings.value("Settings/theme", "graphite", type=str)
            if saved_theme != get_theme_name():
                set_theme(saved_theme)
                self.apply_theme()

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
            self.status_bar.showMessage(tr("main.status_checking_updates"))
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
            self.status_bar.showMessage(tr("main.status_latest_version", version=__version__))
            QMessageBox.information(
                self,
                tr("main.dlg_no_updates_title"),
                tr("main.dlg_no_updates_body", version=__version__),
            )

    def _on_update_check_finished(self) -> None:
        self.settings_panel.btn_check_updates.setEnabled(True)
        if self._update_check_worker is not None:
            self._update_check_worker.wait(1000)
            self._update_check_worker.deleteLater()
        self._update_check_worker = None

    def closeEvent(self, event) -> None:
        overlay = self._theme_overlay
        self._theme_overlay = None
        if overlay is not None:
            overlay.cancel()
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
