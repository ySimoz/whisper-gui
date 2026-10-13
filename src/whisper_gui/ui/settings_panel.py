"""Settings panel for Whisper model, language, hardware, memory management, and export."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.models import TranscriptionConfig
from whisper_gui.transcriber import estimate_model_ram_mb, is_model_downloaded_on_disk

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


class SettingsPanel(QWidget):
    """Panel configuring model parameters, memory management, and document export."""

    settings_changed = Signal()
    free_ram_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._custom_output_dir: Path | None = None
        self._build_ui()
        self._update_disk_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 8, 10, 8)

        # 2-column compact grid for parameters
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)

        # Column 0: Model
        grid.addWidget(QLabel("Whisper Model:"), 0, 0)
        model_vbox = QVBoxLayout()
        model_vbox.setSpacing(2)
        self.combo_model = QComboBox()
        for label, model_id in SUPPORTED_MODELS:
            self.combo_model.addItem(label, model_id)
        self.combo_model.setCurrentIndex(0)  # Default large-v3-turbo
        model_vbox.addWidget(self.combo_model)

        self.lbl_disk_status = QLabel("✓ Downloaded locally")
        self.lbl_disk_status.setStyleSheet("color: #27ae60; font-size: 10px; font-weight: bold;")
        model_vbox.addWidget(self.lbl_disk_status)
        grid.addLayout(model_vbox, 0, 1)

        # Column 1: Language
        grid.addWidget(QLabel("Language:"), 0, 2)
        self.combo_lang = QComboBox()
        for label, code in SUPPORTED_LANGUAGES:
            self.combo_lang.addItem(label, code)
        self.combo_lang.setCurrentIndex(0)  # Default Auto-detect
        grid.addWidget(self.combo_lang, 0, 3)

        # Column 0: Device & Compute Type
        grid.addWidget(QLabel("Device & Type:"), 1, 0)
        dev_layout = QHBoxLayout()
        dev_layout.setSpacing(4)
        self.combo_device = QComboBox()
        self.combo_device.addItem("CPU", "cpu")
        self.combo_device.addItem("CUDA (GPU)", "cuda")
        self.combo_device.setCurrentIndex(0)
        dev_layout.addWidget(self.combo_device)

        self.combo_compute = QComboBox()
        self.combo_compute.addItem("int8 (Fastest on CPU)", "int8")
        self.combo_compute.addItem("float16 (GPU)", "float16")
        self.combo_compute.addItem("float32", "float32")
        self.combo_compute.setCurrentIndex(0)
        dev_layout.addWidget(self.combo_compute)
        grid.addLayout(dev_layout, 1, 1)

        # Column 1: CPU Threads
        grid.addWidget(QLabel("CPU Threads:"), 1, 2)
        max_cpu = os.cpu_count() or 6
        default_threads = min(6, max_cpu)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, max_cpu)
        self.spin_threads.setValue(default_threads)
        self.spin_threads.setToolTip("Number of CPU threads for inference (recommended 6 for physical cores)")
        grid.addWidget(self.spin_threads, 1, 3)

        # Row 2: Checkboxes
        self.chk_vad = QCheckBox("Voice Activity Detection (VAD - skip silence)")
        self.chk_vad.setChecked(True)
        grid.addWidget(self.chk_vad, 2, 0, 1, 2)

        self.chk_timestamps = QCheckBox("Include timestamps in Word document")
        self.chk_timestamps.setChecked(True)
        grid.addWidget(self.chk_timestamps, 2, 2, 1, 2)

        layout.addLayout(grid)

        # Memory & RAM Management Row
        mem_frame = QFrame()
        mem_frame.setFrameShape(QFrame.StyledPanel)
        mem_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #e9ecef;
                border-radius: 4px;
            }
        """)
        mem_layout = QHBoxLayout(mem_frame)
        mem_layout.setContentsMargins(8, 4, 8, 4)
        mem_layout.setSpacing(10)

        self.lbl_ram_status = QLabel("🧠 Model in RAM: None (0 MB)")
        self.lbl_ram_status.setStyleSheet("font-size: 11px; color: #495057;")
        mem_layout.addWidget(self.lbl_ram_status)

        self.btn_free_ram = QPushButton("🧹 Free RAM (Unload Model)")
        self.btn_free_ram.setToolTip("Removes the active model from memory and frees RAM")
        self.btn_free_ram.setMaximumHeight(24)
        self.btn_free_ram.setEnabled(False)
        self.btn_free_ram.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        mem_layout.addWidget(self.btn_free_ram)

        self.chk_auto_unload = QCheckBox("Auto-unload model after transcription finishes")
        self.chk_auto_unload.setStyleSheet("font-size: 11px; color: #6c757d;")
        self.chk_auto_unload.setToolTip("Automatically frees model from RAM when all jobs finish")
        mem_layout.addWidget(self.chk_auto_unload)
        mem_layout.addStretch()

        layout.addWidget(mem_frame)

        # Custom Output Directory Row
        out_layout = QHBoxLayout()
        out_layout.setSpacing(6)
        out_lbl = QLabel("Output Folder:")
        out_lbl.setStyleSheet("font-size: 11px;")
        out_layout.addWidget(out_lbl)

        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText("Default: Same directory as audio file")
        self.txt_output_dir.setReadOnly(True)
        out_layout.addWidget(self.txt_output_dir, stretch=1)

        self.btn_browse_dir = QPushButton("Browse...")
        self.btn_browse_dir.setMaximumHeight(24)
        out_layout.addWidget(self.btn_browse_dir)

        self.btn_clear_dir = QPushButton("Reset")
        self.btn_clear_dir.setMaximumHeight(24)
        out_layout.addWidget(self.btn_clear_dir)

        layout.addLayout(out_layout)

        # Connect signals
        self.combo_model.currentIndexChanged.connect(self._on_model_selected)
        self.combo_lang.currentIndexChanged.connect(self._on_setting_changed)
        self.combo_device.currentIndexChanged.connect(self._on_device_changed)
        self.combo_compute.currentIndexChanged.connect(self._on_setting_changed)
        self.spin_threads.valueChanged.connect(self._on_setting_changed)
        self.chk_vad.toggled.connect(self._on_setting_changed)
        self.chk_timestamps.toggled.connect(self._on_setting_changed)
        self.chk_auto_unload.toggled.connect(self._on_setting_changed)
        self.btn_free_ram.clicked.connect(self.free_ram_requested.emit)

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
            self.lbl_disk_status.setText(f"✓ Downloaded on disk (Instant load, ~{est_mb}MB RAM)")
            self.lbl_disk_status.setStyleSheet("color: #27ae60; font-size: 10px; font-weight: bold;")
        else:
            self.lbl_disk_status.setText(f"📥 Downloads once on first run (~{est_mb}MB)")
            self.lbl_disk_status.setStyleSheet("color: #e67e22; font-size: 10px; font-weight: bold;")

    def set_ram_status(self, is_loaded: bool, model_name: str | None = None) -> None:
        """Update the RAM display badge and enable/disable the Free RAM button."""
        if is_loaded and model_name:
            est_mb = estimate_model_ram_mb(model_name)
            self.lbl_ram_status.setText(f"🧠 Model in RAM: {model_name} (~{est_mb} MB)")
            self.lbl_ram_status.setStyleSheet("font-size: 11px; color: #1a5276; font-weight: bold;")
            self.btn_free_ram.setEnabled(True)
        else:
            self.lbl_ram_status.setText("🧠 Model in RAM: None (0 MB)")
            self.lbl_ram_status.setStyleSheet("font-size: 11px; color: #495057;")
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
            auto_unload_model=self.chk_auto_unload.isChecked(),
        )
