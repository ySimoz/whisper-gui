"""Settings panel for Whisper model, language, hardware, memory management, and export."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whisper_gui import __version__
from whisper_gui.models import TranscriptionConfig
from whisper_gui.transcriber import (
    delete_cached_model,
    estimate_model_ram_mb,
    get_model_cache_size_mb,
    is_model_downloaded_on_disk,
)
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_SECONDARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
)

_SECTION_LABEL_STYLE = f"color: {COLOR_TEXT_MAIN}; font-size: 16px; font-weight: 500; padding: 0;"
_FIELD_LABEL_STYLE = f"color: {COLOR_TEXT_SECONDARY}; font-size: 13px; font-weight: 500; padding: 0;"

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

SUPPORTED_MODELS = [
    ("large-v3-turbo (Highest Accuracy & Speed)", "large-v3-turbo"),
    ("large-v3 (Highest Accuracy)", "large-v3"),
    ("medium (Balanced)", "medium"),
    ("small (Fast Multilingual)", "small"),
    ("base (Very Fast)", "base"),
    ("tiny (Ultra Fast / Testing)", "tiny"),
]


class ThreadComboBox(QComboBox):
    """Popup selection dropdown for CPU threads with value() and setValue() compatibility."""

    valueChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setView(QListView())
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_panel")
        self.setStyleSheet("#settings_panel { background-color: transparent; }")
        self._custom_output_dir: Path | None = None
        self._build_ui()
        self._update_disk_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Section 1: Speech Recognition
        sec_rec = QLabel("Speech Recognition")
        sec_rec.setStyleSheet(_SECTION_LABEL_STYLE)
        layout.addWidget(sec_rec)

        lbl_model = QLabel("Whisper Model")
        lbl_model.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_model)

        self.combo_model = QComboBox()
        self.combo_model.setView(QListView())
        for label, model_id in SUPPORTED_MODELS:
            self.combo_model.addItem(label, model_id)
        self.combo_model.setCurrentIndex(0)
        self.combo_model.setFixedHeight(36)
        layout.addWidget(self.combo_model)

        disk_row = QHBoxLayout()
        disk_row.setSpacing(12)
        self.lbl_disk_status = QLabel("Downloaded locally")
        self.lbl_disk_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        disk_row.addWidget(self.lbl_disk_status, stretch=1)

        self.btn_delete_model = QPushButton("Delete Cached Model")
        self.btn_delete_model.setFixedHeight(32)
        self.btn_delete_model.setEnabled(False)
        disk_row.addWidget(self.btn_delete_model)
        layout.addLayout(disk_row)

        layout.addSpacing(4)

        lbl_lang = QLabel("Language")
        lbl_lang.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_lang)

        self.combo_lang = QComboBox()
        self.combo_lang.setView(QListView())
        for label, code in SUPPORTED_LANGUAGES:
            self.combo_lang.addItem(label, code)
        self.combo_lang.setCurrentIndex(0)
        self.combo_lang.setFixedHeight(36)
        layout.addWidget(self.combo_lang)

        layout.addSpacing(4)

        lbl_dev = QLabel("Inference Device & Compute Type")
        lbl_dev.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_dev)

        dev_row = QHBoxLayout()
        dev_row.setSpacing(12)
        self.combo_device = QComboBox()
        self.combo_device.setView(QListView())
        if sys.platform == "darwin":
            self.combo_device.addItem("CPU (Apple Silicon / Intel)", "cpu")
        else:
            self.combo_device.addItem("CPU", "cpu")
            self.combo_device.addItem("CUDA (GPU)", "cuda")
        self.combo_device.setCurrentIndex(0)
        self.combo_device.setFixedHeight(36)
        dev_row.addWidget(self.combo_device, stretch=2)

        self.combo_compute = QComboBox()
        self.combo_compute.setView(QListView())
        self.combo_compute.addItem("int8 (Fastest on CPU)", "int8")
        self.combo_compute.addItem("float16 (GPU)", "float16")
        self.combo_compute.addItem("float32", "float32")
        self.combo_compute.setCurrentIndex(0)
        self.combo_compute.setFixedHeight(36)
        dev_row.addWidget(self.combo_compute, stretch=2)
        layout.addLayout(dev_row)

        layout.addSpacing(4)

        lbl_threads = QLabel("CPU Threads")
        lbl_threads.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_threads)

        max_cpu = os.cpu_count() or 6
        default_threads = min(6, max_cpu)
        self.spin_threads = ThreadComboBox()
        for t in range(1, max_cpu + 1):
            label = f"{t} thread" if t == 1 else f"{t} threads"
            if t == default_threads:
                label += " (Recommended)"
            self.spin_threads.addItem(label, t)
        self.spin_threads.setValue(default_threads)
        self.spin_threads.setFixedHeight(36)
        self.spin_threads.setToolTip("Number of CPU threads for inference")
        self.combo_threads = self.spin_threads
        layout.addWidget(self.spin_threads)

        layout.addSpacing(4)

        self.chk_vad = QCheckBox("Voice Activity Detection (skip silence)")
        self.chk_vad.setChecked(True)
        layout.addWidget(self.chk_vad)

        self.chk_timestamps = QCheckBox("Include timestamps in Word document")
        self.chk_timestamps.setChecked(True)
        layout.addWidget(self.chk_timestamps)

        layout.addSpacing(16)

        # Section 2: Storage & Output
        sec_out = QLabel("Storage & Output")
        sec_out.setStyleSheet(_SECTION_LABEL_STYLE)
        layout.addWidget(sec_out)

        lbl_out = QLabel("Output Folder")
        lbl_out.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_out)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText("Default: Same folder as original audio")
        self.txt_output_dir.setReadOnly(True)
        self.txt_output_dir.setFixedHeight(36)
        out_row.addWidget(self.txt_output_dir, stretch=1)

        self.btn_browse_dir = QPushButton("Browse")
        self.btn_browse_dir.setFixedHeight(36)
        out_row.addWidget(self.btn_browse_dir)

        self.btn_clear_dir = QPushButton("Reset")
        self.btn_clear_dir.setFixedHeight(36)
        out_row.addWidget(self.btn_clear_dir)
        layout.addLayout(out_row)

        layout.addSpacing(4)

        lbl_fmt = QLabel("Default Export Format")
        lbl_fmt.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_fmt)

        self.combo_export_format = QComboBox()
        self.combo_export_format.setView(QListView())
        self.combo_export_format.addItem("Word Document (.docx)", "docx")
        self.combo_export_format.addItem("PDF Document (.pdf)", "pdf")
        self.combo_export_format.addItem("Markdown (.md)", "md")
        self.combo_export_format.addItem("Plain Text (.txt)", "txt")
        self.combo_export_format.addItem("Subtitles (.srt)", "srt")
        self.combo_export_format.addItem("WebVTT (.vtt)", "vtt")
        self.combo_export_format.setCurrentIndex(0)
        self.combo_export_format.setFixedHeight(36)
        layout.addWidget(self.combo_export_format)

        self.chk_auto_export = QCheckBox("Auto-export file when transcription finishes")
        self.chk_auto_export.setChecked(True)
        self.chk_auto_export.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background-color: transparent;")
        layout.addWidget(self.chk_auto_export)

        layout.addSpacing(16)

        # Section 3: Memory & Performance
        sec_mem = QLabel("System & Memory")
        sec_mem.setStyleSheet(_SECTION_LABEL_STYLE)
        layout.addWidget(sec_mem)

        lbl_ram = QLabel("Model Memory Usage")
        lbl_ram.setStyleSheet(_FIELD_LABEL_STYLE)
        layout.addWidget(lbl_ram)

        ram_row = QHBoxLayout()
        ram_row.setSpacing(12)
        self.lbl_ram_status = QLabel("Model in RAM: None (0 MB)")
        self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        ram_row.addWidget(self.lbl_ram_status, stretch=1)

        self.btn_free_ram = QPushButton("Unload Model")
        self.btn_free_ram.setFixedHeight(32)
        self.btn_free_ram.setEnabled(False)
        ram_row.addWidget(self.btn_free_ram)
        layout.addLayout(ram_row)

        self.chk_auto_unload = QCheckBox("Auto-unload model after transcription finishes")
        self.chk_auto_unload.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED}; background-color: transparent;")
        layout.addWidget(self.chk_auto_unload)

        update_row = QHBoxLayout()
        update_row.setSpacing(12)
        self.lbl_version = QLabel(f"Version {__version__}")
        self.lbl_version.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
        update_row.addWidget(self.lbl_version, stretch=1)

        self.btn_check_updates = QPushButton("Check for Updates")
        self.btn_check_updates.setFixedHeight(32)
        update_row.addWidget(self.btn_check_updates)
        layout.addLayout(update_row)

        layout.addStretch()

        # Connect signals
        self.combo_model.currentIndexChanged.connect(self._on_model_selected)
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

    def _on_model_selected(self) -> None:
        self._update_disk_status()
        self._on_setting_changed()

    def _update_disk_status(self) -> None:
        model_name = str(self.combo_model.currentData())
        is_downloaded = is_model_downloaded_on_disk(model_name)
        est_mb = estimate_model_ram_mb(model_name)
        if is_downloaded:
            size_mb = get_model_cache_size_mb(model_name)
            size_str = f"{size_mb:.0f} MB on disk" if size_mb >= 1 else f"{size_mb:.1f} MB on disk"
            self.lbl_disk_status.setText(f"Downloaded on disk ({size_str}, ~{est_mb}MB RAM)")
            self.lbl_disk_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
            self.btn_delete_model.setEnabled(True)
        else:
            self.lbl_disk_status.setText(f"Not cached locally (~{est_mb}MB download)")
            self.lbl_disk_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
            self.btn_delete_model.setEnabled(False)

    def _on_delete_model_clicked(self) -> None:
        model_name = str(self.combo_model.currentData())
        size_mb = get_model_cache_size_mb(model_name)
        reply = QMessageBox.question(
            self,
            "Delete Cached Model",
            f"Delete cached '{model_name}' model files (~{size_mb:.1f} MB) from disk?\n\n"
            "You can re-download it anytime by transcribing with this model.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        delete_cached_model(model_name)
        self._update_disk_status()

    def set_ram_status(self, is_loaded: bool, model_name: str | None = None) -> None:
        """Update the RAM display badge and enable/disable the Free RAM button."""
        if is_loaded and model_name:
            est_mb = estimate_model_ram_mb(model_name)
            self.lbl_ram_status.setText(f"Model in Memory: {model_name} (~{est_mb} MB)")
            self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MAIN}; font-weight: 500;")
            self.btn_free_ram.setEnabled(True)
        else:
            self.lbl_ram_status.setText("Model in Memory: None (0 MB)")
            self.lbl_ram_status.setStyleSheet(f"font-size: 12px; color: {COLOR_TEXT_MUTED};")
            self.btn_free_ram.setEnabled(False)

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
        chosen = QFileDialog.getExistingDirectory(self, "Select Output Directory for Word Documents")
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
        settings.endGroup()

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
