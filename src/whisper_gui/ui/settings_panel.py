"""Settings panel for Whisper model, language, hardware, memory management, and export."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whisper_gui import __version__
from whisper_gui.i18n import SUPPORTED_APP_LANGUAGES, get_language, tr
from whisper_gui.models import TranscriptionConfig
from whisper_gui.transcriber import (
    delete_cached_model,
    estimate_model_ram_mb,
    get_model_cache_size_mb,
    is_model_downloaded_on_disk,
)
from whisper_gui.ui.theme import (
    ToggleSwitch,
    fixed_mono_font,
    get_palette,
    get_theme_name,
    load_ui_icon,
    style_combobox,
    swatch_icon,
)
from whisper_gui.worker import ModelDownloadWorker

SUPPORTED_LANGUAGES = [
    ("Auto-detect", None),
    ("Italian (it)", "it"),
    ("English (en)", "en"),
    ("Spanish (es)", "es"),
    ("French (fr)", "fr"),
    ("German (de)", "de"),
    ("Portuguese (pt)", "pt"),
    ("Chinese (zh)", "zh"),
    ("Japanese (ja)", "ja"),
    ("Russian (ru)", "ru"),
    ("Arabic (ar)", "ar"),
    ("Dutch (nl)", "nl"),
    ("Polish (pl)", "pl"),
]

_LANGUAGE_KEY_MAP: dict[str | None, str] = {
    None: "settings.lang_auto",
    "it": "settings.lang_it",
    "en": "settings.lang_en",
    "es": "settings.lang_es",
    "fr": "settings.lang_fr",
    "de": "settings.lang_de",
    "pt": "settings.lang_pt",
    "zh": "settings.lang_zh",
    "ja": "settings.lang_ja",
    "ru": "settings.lang_ru",
    "ar": "settings.lang_ar",
    "nl": "settings.lang_nl",
    "pl": "settings.lang_pl",
}

SUPPORTED_MODELS = [
    ("large-v3-turbo (Highest Accuracy & Speed)", "large-v3-turbo"),
    ("large-v3 (Highest Accuracy)", "large-v3"),
    ("medium (Balanced)", "medium"),
    ("small (Fast Multilingual)", "small"),
    ("base (Very Fast)", "base"),
    ("tiny (Ultra Fast / Testing)", "tiny"),
]

_MODEL_KEY_MAP: dict[str, str] = {
    "large-v3-turbo": "settings.model_large_v3_turbo",
    "large-v3": "settings.model_large_v3",
    "medium": "settings.model_medium",
    "small": "settings.model_small",
    "base": "settings.model_base",
    "tiny": "settings.model_tiny",
}

_EXPORT_FORMAT_KEYS: list[tuple[str, str]] = [
    ("docx", "settings.fmt_docx"),
    ("pdf", "settings.fmt_pdf"),
    ("md", "settings.fmt_md"),
    ("txt", "settings.fmt_txt"),
    ("srt", "settings.fmt_srt"),
    ("vtt", "settings.fmt_vtt"),
]


class ThreadComboBox(QComboBox):
    """Popup selection dropdown for CPU threads with value() and setValue() compatibility."""

    valueChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        style_combobox(self)
        self.currentIndexChanged.connect(self._emit_value_changed)

    def _emit_value_changed(self) -> None:
        self.valueChanged.emit(self.value())

    def value(self) -> int:
        data = self.currentData()
        return int(data) if data is not None else 4

    def setValue(self, val: int) -> None:
        idx = self.findData(val)
        if idx >= 0:
            self.setCurrentIndex(idx)


class SettingsPanel(QWidget):
    """Panel configuring model parameters, memory management, and document export."""

    settings_changed = Signal()
    free_ram_requested = Signal()
    check_updates_requested = Signal()
    theme_changed = Signal(str, object)
    app_language_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_panel")
        self.setStyleSheet("#settings_panel { background-color: transparent; }")
        self._custom_output_dir: Path | None = None
        self._ram_loaded = False
        self._ram_model_name: str | None = None
        self._download_worker: ModelDownloadWorker | None = None
        self._section_labels: list[QLabel] = []
        self._field_labels: list[QLabel] = []
        self._section_label_keys: list[tuple[QLabel, str]] = []
        self._field_label_keys: list[tuple[QLabel, str]] = []
        self._muted_labels: list[QLabel] = []
        self._toggle_switches: list[QCheckBox] = []
        self._build_ui()
        self.apply_theme()
        self._update_disk_status()

    def _make_section_label(self, key: str) -> QLabel:
        lbl = QLabel(tr(key))
        self._section_labels.append(lbl)
        self._section_label_keys.append((lbl, key))
        return lbl

    def _make_field_label(self, key: str) -> QLabel:
        lbl = QLabel(tr(key))
        self._field_labels.append(lbl)
        self._field_label_keys.append((lbl, key))
        return lbl

    def _add_field_group(self, parent_layout: QVBoxLayout, label_key: str, item: object) -> None:
        """Group a field label and its control with a 4px inner gap."""
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(4)
        group.addWidget(self._make_field_label(label_key))
        if isinstance(item, QWidget):
            group.addWidget(item)
        else:
            group.addLayout(item)
        parent_layout.addLayout(group)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Appearance
        layout.addWidget(self._make_section_label("settings.sec_appearance"))

        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        self.theme_btn_group = QButtonGroup(self)
        self.theme_btn_group.setExclusive(True)

        self.btn_theme_graphite = QPushButton(tr("settings.theme_graphite"))
        self.btn_theme_graphite.setCheckable(True)
        self.btn_theme_graphite.setIcon(swatch_icon("#141415", "#232325", "#3C3C40"))
        self.btn_theme_graphite.setIconSize(QSize(14, 14))
        self.btn_theme_graphite.setFixedHeight(36)
        self.btn_theme_graphite.clicked.connect(
            lambda: self._on_theme_button_clicked("graphite", self.btn_theme_graphite)
        )
        self.theme_btn_group.addButton(self.btn_theme_graphite)
        theme_row.addWidget(self.btn_theme_graphite, stretch=1)

        self.btn_theme_blush = QPushButton(tr("settings.theme_blush"))
        self.btn_theme_blush.setCheckable(True)
        self.btn_theme_blush.setIcon(swatch_icon("#F8C8DC", "#F3CFC6", "#C99AAE"))
        self.btn_theme_blush.setIconSize(QSize(14, 14))
        self.btn_theme_blush.setFixedHeight(36)
        self.btn_theme_blush.clicked.connect(
            lambda: self._on_theme_button_clicked("blush", self.btn_theme_blush)
        )
        self.theme_btn_group.addButton(self.btn_theme_blush)
        theme_row.addWidget(self.btn_theme_blush, stretch=1)

        self._add_field_group(layout, "settings.color_theme", theme_row)

        self.combo_app_language = QComboBox()
        style_combobox(self.combo_app_language)
        for lang_code, lang_label in SUPPORTED_APP_LANGUAGES:
            self.combo_app_language.addItem(lang_label, lang_code)
        self.combo_app_language.setFixedHeight(36)
        self.set_selected_app_language(get_language())
        self._add_field_group(layout, "settings.app_language", self.combo_app_language)

        layout.addSpacing(12)

        # Section 1: Speech Recognition
        layout.addWidget(self._make_section_label("settings.sec_recognition"))

        self.combo_model = QComboBox()
        style_combobox(self.combo_model)
        for label, model_id in SUPPORTED_MODELS:
            key = _MODEL_KEY_MAP.get(model_id)
            self.combo_model.addItem(tr(key) if key else label, model_id)
        self.combo_model.setCurrentIndex(0)
        self.combo_model.setFixedHeight(36)

        disk_row = QHBoxLayout()
        disk_row.setSpacing(8)
        self.lbl_disk_status = QLabel(tr("settings.disk_downloaded_short"))
        self._muted_labels.append(self.lbl_disk_status)
        disk_row.addWidget(self.lbl_disk_status, stretch=1)

        self.btn_download_model = QPushButton(tr("settings.download_model_btn"))
        self.btn_download_model.setIconSize(QSize(16, 16))
        self.btn_download_model.setFixedHeight(32)
        disk_row.addWidget(self.btn_download_model)

        self.btn_delete_model = QPushButton(tr("settings.delete_model_btn"))
        self.btn_delete_model.setFixedHeight(32)
        self.btn_delete_model.setEnabled(False)
        disk_row.addWidget(self.btn_delete_model)

        self.model_download_bar = QProgressBar()
        self.model_download_bar.setRange(0, 100)
        self.model_download_bar.setValue(0)
        self.model_download_bar.setTextVisible(False)
        self.model_download_bar.setFixedHeight(4)
        self.model_download_bar.setVisible(False)

        self.lbl_download_progress = QLabel("")
        self.lbl_download_progress.setFont(fixed_mono_font(11))
        self.lbl_download_progress.setVisible(False)

        model_group = QVBoxLayout()
        model_group.setContentsMargins(0, 0, 0, 0)
        model_group.setSpacing(8)
        model_group.addWidget(self.combo_model)
        model_group.addLayout(disk_row)
        model_group.addWidget(self.model_download_bar)
        model_group.addWidget(self.lbl_download_progress)
        self._add_field_group(layout, "settings.whisper_model", model_group)

        self.combo_lang = QComboBox()
        style_combobox(self.combo_lang)
        for label, code in SUPPORTED_LANGUAGES:
            key = _LANGUAGE_KEY_MAP.get(code)
            self.combo_lang.addItem(tr(key) if key else label, code)
        self.combo_lang.setCurrentIndex(0)
        self.combo_lang.setFixedHeight(36)
        self._add_field_group(layout, "settings.transcription_language", self.combo_lang)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(8)
        self.combo_device = QComboBox()
        style_combobox(self.combo_device)
        if sys.platform == "darwin":
            self.combo_device.addItem(tr("settings.device_cpu_mac"), "cpu")
        else:
            self.combo_device.addItem(tr("settings.device_cpu"), "cpu")
            self.combo_device.addItem(tr("settings.device_cuda"), "cuda")
        self.combo_device.setCurrentIndex(0)
        self.combo_device.setFixedHeight(36)
        dev_row.addWidget(self.combo_device, stretch=2)

        self.combo_compute = QComboBox()
        style_combobox(self.combo_compute)
        self.combo_compute.addItem(tr("settings.compute_int8"), "int8")
        self.combo_compute.addItem(tr("settings.compute_float16"), "float16")
        self.combo_compute.addItem(tr("settings.compute_float32"), "float32")
        self.combo_compute.setCurrentIndex(0)
        self.combo_compute.setFixedHeight(36)
        dev_row.addWidget(self.combo_compute, stretch=2)
        self._add_field_group(layout, "settings.device_compute", dev_row)

        max_cpu = os.cpu_count() or 6
        default_threads = min(6, max_cpu)
        self.spin_threads = ThreadComboBox()
        self._populate_thread_items(max_cpu, default_threads)
        self.spin_threads.setValue(default_threads)
        self.spin_threads.setFixedHeight(36)
        self.spin_threads.setToolTip(tr("settings.threads_tooltip"))
        self.combo_threads = self.spin_threads
        self._add_field_group(layout, "settings.cpu_threads", self.spin_threads)

        self.chk_vad = ToggleSwitch(tr("settings.chk_vad"))
        self.chk_vad.setChecked(True)
        self._toggle_switches.append(self.chk_vad)
        layout.addWidget(self.chk_vad)

        self.chk_timestamps = ToggleSwitch(tr("settings.chk_timestamps"))
        self.chk_timestamps.setChecked(True)
        self._toggle_switches.append(self.chk_timestamps)
        layout.addWidget(self.chk_timestamps)

        layout.addSpacing(12)

        # Section 2: Storage & Output
        layout.addWidget(self._make_section_label("settings.sec_storage"))

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText(tr("settings.output_placeholder"))
        self.txt_output_dir.setReadOnly(True)
        self.txt_output_dir.setFixedHeight(36)
        out_row.addWidget(self.txt_output_dir, stretch=1)

        self.btn_browse_dir = QPushButton(tr("settings.browse_btn"))
        self.btn_browse_dir.setFixedHeight(36)
        out_row.addWidget(self.btn_browse_dir)

        self.btn_clear_dir = QPushButton(tr("settings.reset_btn"))
        self.btn_clear_dir.setFixedHeight(36)
        out_row.addWidget(self.btn_clear_dir)
        self._add_field_group(layout, "settings.output_folder", out_row)

        self.combo_export_format = QComboBox()
        style_combobox(self.combo_export_format)
        for fmt_code, fmt_key in _EXPORT_FORMAT_KEYS:
            self.combo_export_format.addItem(tr(fmt_key), fmt_code)
        self.combo_export_format.setCurrentIndex(0)
        self.combo_export_format.setFixedHeight(36)
        self._add_field_group(layout, "settings.export_format", self.combo_export_format)

        self.chk_auto_export = ToggleSwitch(tr("settings.chk_auto_export"))
        self.chk_auto_export.setChecked(True)
        self._toggle_switches.append(self.chk_auto_export)
        layout.addWidget(self.chk_auto_export)

        layout.addSpacing(12)

        # Section 3: Memory & Performance
        layout.addWidget(self._make_section_label("settings.sec_system"))

        ram_row = QHBoxLayout()
        ram_row.setSpacing(12)
        self.lbl_ram_status = QLabel(tr("settings.ram_none"))
        ram_row.addWidget(self.lbl_ram_status, stretch=1)

        self.btn_free_ram = QPushButton(tr("settings.unload_model_btn"))
        self.btn_free_ram.setFixedHeight(32)
        self.btn_free_ram.setEnabled(False)
        ram_row.addWidget(self.btn_free_ram)
        self._add_field_group(layout, "settings.model_memory", ram_row)

        self.chk_auto_unload = ToggleSwitch(tr("settings.chk_auto_unload"))
        self._toggle_switches.append(self.chk_auto_unload)
        layout.addWidget(self.chk_auto_unload)

        update_row = QHBoxLayout()
        update_row.setSpacing(12)
        self.lbl_version = QLabel(tr("settings.version", version=__version__))
        self._muted_labels.append(self.lbl_version)
        update_row.addWidget(self.lbl_version, stretch=1)

        self.btn_check_updates = QPushButton(tr("settings.check_updates_btn"))
        self.btn_check_updates.setFixedHeight(32)
        update_row.addWidget(self.btn_check_updates)
        layout.addLayout(update_row)

        layout.addStretch()

        # Connect signals
        self.combo_app_language.currentIndexChanged.connect(self._on_app_language_selected)
        self.combo_model.currentIndexChanged.connect(self._on_model_selected)
        self.btn_download_model.clicked.connect(self._on_download_model_clicked)
        self.btn_delete_model.clicked.connect(self._on_delete_model_clicked)
        self.combo_lang.currentIndexChanged.connect(self._on_setting_changed)
        self.combo_device.currentIndexChanged.connect(self._on_device_changed)
        self.combo_compute.currentIndexChanged.connect(self._on_setting_changed)
        self.spin_threads.valueChanged.connect(self._on_setting_changed)
        self.chk_vad.toggled.connect(self._on_setting_changed)
        self.chk_timestamps.toggled.connect(self._on_setting_changed)
        self.combo_export_format.currentIndexChanged.connect(self._on_setting_changed)
        self.chk_auto_export.toggled.connect(self._on_setting_changed)
        self.chk_auto_unload.toggled.connect(self._on_setting_changed)
        self.btn_free_ram.clicked.connect(self.free_ram_requested.emit)
        self.btn_check_updates.clicked.connect(self.check_updates_requested.emit)

        self.btn_browse_dir.clicked.connect(self._choose_output_dir)
        self.btn_clear_dir.clicked.connect(self._reset_output_dir)

    def _populate_thread_items(self, max_cpu: int, default_threads: int) -> None:
        self.spin_threads.blockSignals(True)
        current_val = self.spin_threads.value() if self.spin_threads.count() else default_threads
        self.spin_threads.clear()
        for t in range(1, max_cpu + 1):
            label = tr("settings.thread_singular", count=t) if t == 1 else tr("settings.thread_plural", count=t)
            if t == default_threads:
                label += tr("settings.recommended_suffix")
            self.spin_threads.addItem(label, t)
        self.spin_threads.setValue(current_val)
        self.spin_threads.blockSignals(False)

    def _on_app_language_selected(self) -> None:
        lang = str(self.combo_app_language.currentData() or "en")
        self.app_language_changed.emit(lang)

    def set_selected_app_language(self, lang_code: str) -> None:
        """Reflect active app language on dropdown without emitting app_language_changed."""
        self.combo_app_language.blockSignals(True)
        idx = self.combo_app_language.findData(lang_code)
        if idx >= 0:
            self.combo_app_language.setCurrentIndex(idx)
        self.combo_app_language.blockSignals(False)

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        for lbl, key in self._section_label_keys:
            lbl.setText(tr(key))
        for lbl, key in self._field_label_keys:
            lbl.setText(tr(key))

        self.btn_theme_graphite.setText(tr("settings.theme_graphite"))
        self.btn_theme_blush.setText(tr("settings.theme_blush"))
        self.set_selected_app_language(get_language())

        for i in range(self.combo_model.count()):
            model_id = str(self.combo_model.itemData(i))
            if model_id in _MODEL_KEY_MAP:
                self.combo_model.setItemText(i, tr(_MODEL_KEY_MAP[model_id]))

        self.btn_download_model.setText(
            tr("settings.cancel_download_btn")
            if self._download_worker and self._download_worker.isRunning()
            else tr("settings.download_model_btn")
        )
        self.btn_delete_model.setText(tr("settings.delete_model_btn"))
        self._update_disk_status()

        for i in range(self.combo_lang.count()):
            code = self.combo_lang.itemData(i)
            if code in _LANGUAGE_KEY_MAP:
                self.combo_lang.setItemText(i, tr(_LANGUAGE_KEY_MAP[code]))

        for i in range(self.combo_device.count()):
            dev = self.combo_device.itemData(i)
            if dev == "cpu":
                key = "settings.device_cpu_mac" if sys.platform == "darwin" else "settings.device_cpu"
                self.combo_device.setItemText(i, tr(key))
            elif dev == "cuda":
                self.combo_device.setItemText(i, tr("settings.device_cuda"))

        comp_keys = {"int8": "settings.compute_int8", "float16": "settings.compute_float16", "float32": "settings.compute_float32"}
        for i in range(self.combo_compute.count()):
            comp = self.combo_compute.itemData(i)
            if comp in comp_keys:
                self.combo_compute.setItemText(i, tr(comp_keys[comp]))

        max_cpu = os.cpu_count() or 6
        default_threads = min(6, max_cpu)
        self._populate_thread_items(max_cpu, default_threads)
        self.spin_threads.setToolTip(tr("settings.threads_tooltip"))

        self.chk_vad.setText(tr("settings.chk_vad"))
        self.chk_timestamps.setText(tr("settings.chk_timestamps"))
        self.txt_output_dir.setPlaceholderText(tr("settings.output_placeholder"))
        self.btn_browse_dir.setText(tr("settings.browse_btn"))
        self.btn_clear_dir.setText(tr("settings.reset_btn"))

        fmt_map = dict(_EXPORT_FORMAT_KEYS)
        for i in range(self.combo_export_format.count()):
            fmt_code = str(self.combo_export_format.itemData(i))
            if fmt_code in fmt_map:
                self.combo_export_format.setItemText(i, tr(fmt_map[fmt_code]))

        self.chk_auto_export.setText(tr("settings.chk_auto_export"))
        self.btn_free_ram.setText(tr("settings.unload_model_btn"))
        self.set_ram_status(self._ram_loaded, self._ram_model_name)
        self.chk_auto_unload.setText(tr("settings.chk_auto_unload"))
        self.lbl_version.setText(tr("settings.version", version=__version__))
        self.btn_check_updates.setText(tr("settings.check_updates_btn"))

    def _on_model_selected(self) -> None:
        if not (self._download_worker and self._download_worker.isRunning()):
            self.lbl_download_progress.setVisible(False)
        self._update_disk_status()
        self._on_setting_changed()

    def _update_disk_status(self) -> None:
        if self._download_worker and self._download_worker.isRunning():
            return
        model_name = str(self.combo_model.currentData())
        is_downloaded = is_model_downloaded_on_disk(model_name)
        est_mb = estimate_model_ram_mb(model_name)
        if is_downloaded:
            size_mb = get_model_cache_size_mb(model_name)
            size_str = (
                tr("settings.disk_on_disk_int", size=size_mb)
                if size_mb >= 1
                else tr("settings.disk_on_disk_dec", size=size_mb)
            )
            self.lbl_disk_status.setText(
                tr("settings.disk_downloaded_detail", size_str=size_str, ram_mb=est_mb)
            )
            self.btn_delete_model.setEnabled(True)
            self.btn_download_model.setVisible(False)
            self.btn_download_model.setEnabled(False)
        else:
            self.lbl_disk_status.setText(tr("settings.disk_not_cached", ram_mb=est_mb))
            self.btn_delete_model.setEnabled(False)
            self.btn_download_model.setIcon(load_ui_icon("download"))
            self.btn_download_model.setText(tr("settings.download_model_btn"))
            self.btn_download_model.setVisible(True)
            self.btn_download_model.setEnabled(True)

    def _on_download_model_clicked(self) -> None:
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.request_stop()
            self.btn_download_model.setEnabled(False)
            self.lbl_download_progress.setText(tr("settings.download_cancelling"))
            return

        model_name = str(self.combo_model.currentData())
        if not model_name:
            return

        p = get_palette()
        self.combo_model.setEnabled(False)
        self.btn_delete_model.setEnabled(False)
        self.btn_delete_model.setVisible(False)
        self.btn_download_model.setIcon(load_ui_icon("close"))
        self.btn_download_model.setText(tr("settings.cancel_download_btn"))
        self.btn_download_model.setEnabled(True)
        self.model_download_bar.setRange(0, 0)
        self.model_download_bar.setVisible(True)
        self.lbl_disk_status.setText(tr("settings.downloading_model", model=model_name))
        self.lbl_download_progress.setStyleSheet(f"color: {p.text_muted};")
        self.lbl_download_progress.setText(tr("transcriber.downloading_preparing_short"))
        self.lbl_download_progress.setVisible(True)

        self._download_worker = ModelDownloadWorker(model_name=model_name, parent=self)
        self._download_worker.progress_updated.connect(self._on_model_download_progress)
        self._download_worker.status_updated.connect(self._on_model_download_status)
        self._download_worker.completed.connect(self._on_model_download_completed)
        self._download_worker.failed.connect(self._on_model_download_failed)
        self._download_worker.cancelled.connect(self._on_model_download_cancelled)
        self._download_worker.finished.connect(self._on_model_download_finished)
        self._download_worker.start()

    def _on_model_download_progress(self, percent: int, metrics_text: str) -> None:
        if percent < 0:
            if self.model_download_bar.maximum() != 0:
                self.model_download_bar.setRange(0, 0)
        else:
            if self.model_download_bar.minimum() != 0 or self.model_download_bar.maximum() != 100:
                self.model_download_bar.setRange(0, 100)
            self.model_download_bar.setValue(max(0, min(100, percent)))
        if metrics_text:
            self.lbl_download_progress.setText(metrics_text)

    def _on_model_download_status(self, message: str) -> None:
        # Keep disk status line concise while byte metrics live in lbl_download_progress
        if not self.lbl_download_progress.isVisible():
            self.lbl_disk_status.setText(message)

    def _on_model_download_completed(self, model_name: str) -> None:
        self.model_download_bar.setRange(0, 100)
        self.model_download_bar.setValue(100)
        self.model_download_bar.setVisible(False)
        self.lbl_download_progress.setVisible(False)

    def _on_model_download_failed(self, error_msg: str) -> None:
        p = get_palette()
        self.model_download_bar.setRange(0, 100)
        self.model_download_bar.setValue(0)
        self.model_download_bar.setVisible(False)
        self.lbl_download_progress.setStyleSheet(f"color: {p.negative};")
        self.lbl_download_progress.setText(tr("settings.download_failed", error=error_msg))
        self.lbl_download_progress.setVisible(True)

    def _on_model_download_cancelled(self) -> None:
        self.model_download_bar.setRange(0, 100)
        self.model_download_bar.setValue(0)
        self.model_download_bar.setVisible(False)
        self.lbl_download_progress.setVisible(False)

    def _on_model_download_finished(self) -> None:
        worker = self._download_worker
        self._download_worker = None
        if worker is not None:
            worker.wait(1000)
            worker.deleteLater()
        self.combo_model.setEnabled(True)
        self.btn_delete_model.setVisible(True)
        self._update_disk_status()

    def stop_download(self) -> None:
        """Stop any in-flight model download safely during shutdown."""
        if self._download_worker and self._download_worker.isRunning():
            self._download_worker.request_stop()
            self._download_worker.wait(3000)

    def _on_delete_model_clicked(self) -> None:
        model_name = str(self.combo_model.currentData())
        size_mb = get_model_cache_size_mb(model_name)
        reply = QMessageBox.question(
            self,
            tr("settings.delete_model_title"),
            tr("settings.delete_model_body", model=model_name, size=size_mb),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        delete_cached_model(model_name)
        self._update_disk_status()

    def set_ram_status(self, is_loaded: bool, model_name: str | None = None) -> None:
        """Update the RAM display badge and enable/disable the Free RAM button."""
        p = get_palette()
        self._ram_loaded = bool(is_loaded and model_name)
        self._ram_model_name = model_name if self._ram_loaded else None
        if self._ram_loaded:
            est_mb = estimate_model_ram_mb(model_name)
            self.lbl_ram_status.setText(tr("settings.ram_loaded", model=model_name, ram_mb=est_mb))
            self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {p.text_main}; font-weight: 500;")
            self.btn_free_ram.setEnabled(True)
        else:
            self.lbl_ram_status.setText(tr("settings.ram_none"))
            self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {p.text_muted};")
            self.btn_free_ram.setEnabled(False)

    def _on_theme_button_clicked(self, theme_name: str, button: QPushButton) -> None:
        self.theme_changed.emit(theme_name, button)

    def set_selected_theme(self, theme_name: str) -> None:
        """Reflect active theme on selector buttons without emitting theme_changed."""
        self.btn_theme_graphite.setChecked(theme_name != "blush")
        self.btn_theme_blush.setChecked(theme_name == "blush")

    def apply_theme(self) -> None:
        """Apply the active palette across section labels, captions, and theme buttons."""
        p = get_palette()
        sec_style = f"color: {p.text_main}; font-size: 16px; font-weight: 500; padding: 0;"
        field_style = f"color: {p.text_secondary}; font-size: 13px; font-weight: 500; padding: 0;"
        muted_style = f"color: {p.text_muted}; font-size: 12px;"
        toggle_style = f"font-size: 13px; color: {p.text_main}; background-color: transparent;"

        for lbl in self._section_labels:
            lbl.setStyleSheet(sec_style)
        for lbl in self._field_labels:
            lbl.setStyleSheet(field_style)
        for lbl in self._muted_labels:
            lbl.setStyleSheet(muted_style)
        for chk in self._toggle_switches:
            chk.setStyleSheet(toggle_style)

        ram_color = p.text_main if self._ram_loaded else p.text_muted
        ram_weight = " font-weight: 500;" if self._ram_loaded else ""
        self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {ram_color};{ram_weight}")

        btn_style = f"""
            QPushButton {{
                background-color: {p.bg_input};
                color: {p.text_secondary};
                border: 1px solid {p.border};
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 500;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {p.bg_raised};
                color: {p.text_main};
                border: 1px solid {p.border_light};
            }}
            QPushButton:checked {{
                background-color: {p.bg_raised};
                color: {p.text_main};
                border: 1.5px solid {p.primary};
            }}
        """
        self.btn_theme_graphite.setStyleSheet(btn_style)
        self.btn_theme_blush.setStyleSheet(btn_style)
        is_downloading = bool(self._download_worker and self._download_worker.isRunning())
        self.btn_download_model.setIcon(load_ui_icon("close" if is_downloading else "download"))
        self.lbl_download_progress.setStyleSheet(f"color: {p.text_muted};")
        self.set_selected_theme(get_theme_name())

    def _on_device_changed(self) -> None:
        device = self.combo_device.currentData()
        if device == "cuda":
            self.combo_compute.setCurrentIndex(1)  # float16
        else:
            self.combo_compute.setCurrentIndex(0)  # int8
        self._on_setting_changed()

    def _on_setting_changed(self) -> None:
        self.settings_changed.emit()

    def _choose_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("settings.select_output_dir"))
        if chosen:
            self._custom_output_dir = Path(chosen).resolve()
            self.txt_output_dir.setText(str(self._custom_output_dir))
            self._on_setting_changed()

    def _reset_output_dir(self) -> None:
        self._custom_output_dir = None
        self.txt_output_dir.clear()
        self._on_setting_changed()

    def get_config(self) -> TranscriptionConfig:
        """Extract current settings into TranscriptionConfig."""
        return TranscriptionConfig(
            model_name=str(self.combo_model.currentData()),
            device=str(self.combo_device.currentData()),
            compute_type=str(self.combo_compute.currentData()),
            cpu_threads=int(self.spin_threads.value()),
            language=self.combo_lang.currentData(),
            vad_filter=self.chk_vad.isChecked(),
            beam_size=5,
            include_timestamps_in_docx=self.chk_timestamps.isChecked(),
            output_dir=self._custom_output_dir,
            export_format=str(self.combo_export_format.currentData()),
            auto_export=self.chk_auto_export.isChecked(),
            auto_unload_model=self.chk_auto_unload.isChecked(),
        )

    def save_settings(self, settings: QSettings) -> None:
        """Persist settings to QSettings."""
        settings.beginGroup("Settings")
        settings.setValue("model_name", self.combo_model.currentData())
        settings.setValue("language", self.combo_lang.currentData() or "")
        settings.setValue("device", self.combo_device.currentData())
        settings.setValue("compute_type", self.combo_compute.currentData())
        settings.setValue("cpu_threads", self.spin_threads.value())
        settings.setValue("vad_filter", self.chk_vad.isChecked())
        settings.setValue("include_timestamps", self.chk_timestamps.isChecked())
        settings.setValue("export_format", self.combo_export_format.currentData())
        settings.setValue("auto_export", self.chk_auto_export.isChecked())
        settings.setValue("auto_unload", self.chk_auto_unload.isChecked())
        settings.setValue("output_dir", str(self._custom_output_dir) if self._custom_output_dir else "")
        settings.setValue("theme", get_theme_name())
        settings.setValue("app_language", get_language())
        settings.endGroup()

    def load_settings(self, settings: QSettings) -> None:
        """Restore settings from QSettings."""
        settings.beginGroup("Settings")
        model_name = settings.value("model_name", "large-v3-turbo", type=str)
        lang = settings.value("language", "", type=str)
        device = settings.value("device", "cpu", type=str)
        compute = settings.value("compute_type", "int8", type=str)
        threads = settings.value("cpu_threads", self.spin_threads.value(), type=int)
        vad = settings.value("vad_filter", True, type=bool)
        ts = settings.value("include_timestamps", True, type=bool)
        export_fmt = settings.value("export_format", "docx", type=str)
        auto_exp = settings.value("auto_export", True, type=bool)
        auto_unload = settings.value("auto_unload", False, type=bool)
        out_dir = settings.value("output_dir", "", type=str)
        theme_name = settings.value("theme", "graphite", type=str)
        app_lang = settings.value("app_language", "en", type=str)
        settings.endGroup()
        self.set_selected_theme(theme_name)
        self.set_selected_app_language(app_lang)

        idx_model = self.combo_model.findData(model_name)
        if idx_model >= 0:
            self.combo_model.setCurrentIndex(idx_model)

        idx_lang = self.combo_lang.findData(lang if lang else None)
        if idx_lang >= 0:
            self.combo_lang.setCurrentIndex(idx_lang)

        idx_dev = self.combo_device.findData(device)
        if idx_dev >= 0:
            self.combo_device.setCurrentIndex(idx_dev)

        idx_comp = self.combo_compute.findData(compute)
        if idx_comp >= 0:
            self.combo_compute.setCurrentIndex(idx_comp)

        self.spin_threads.setValue(threads)
        self.chk_vad.setChecked(vad)
        self.chk_timestamps.setChecked(ts)
        self.chk_auto_unload.setChecked(auto_unload)

        idx_fmt = self.combo_export_format.findData(export_fmt)
        if idx_fmt >= 0:
            self.combo_export_format.setCurrentIndex(idx_fmt)
        self.chk_auto_export.setChecked(auto_exp)

        if out_dir and Path(out_dir).is_dir():
            self._custom_output_dir = Path(out_dir).resolve()
            self.txt_output_dir.setText(str(self._custom_output_dir))
