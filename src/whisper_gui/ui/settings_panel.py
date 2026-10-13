"""Settings panel for Whisper model, language, hardware, and document export."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.models import TranscriptionConfig

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


class SettingsPanel(QGroupBox):
    """Panel configuring model parameters and document export."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Model & Export Settings", parent)
        self._custom_output_dir: Path | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 14, 12, 12)

        form = QFormLayout()
        form.setSpacing(8)

        # Model Selector
        self.combo_model = QComboBox()
        for label, model_id in SUPPORTED_MODELS:
            self.combo_model.addItem(label, model_id)
        self.combo_model.setCurrentIndex(0)  # Default large-v3-turbo
        form.addRow("Whisper Model:", self.combo_model)

        # Language Selector
        self.combo_lang = QComboBox()
        for label, code in SUPPORTED_LANGUAGES:
            self.combo_lang.addItem(label, code)
        self.combo_lang.setCurrentIndex(0)  # Default Auto-detect
        form.addRow("Language:", self.combo_lang)

        # Device & Compute Type
        device_row = QHBoxLayout()
        self.combo_device = QComboBox()
        self.combo_device.addItem("CPU", "cpu")
        self.combo_device.addItem("CUDA (GPU)", "cuda")
        self.combo_device.setCurrentIndex(0)
        device_row.addWidget(self.combo_device)

        self.combo_compute = QComboBox()
        self.combo_compute.addItem("int8 (Fastest on CPU)", "int8")
        self.combo_compute.addItem("float16 (GPU)", "float16")
        self.combo_compute.addItem("float32", "float32")
        self.combo_compute.setCurrentIndex(0)
        device_row.addWidget(self.combo_compute)

        form.addRow("Device & Type:", device_row)

        # CPU Threads
        max_cpu = os.cpu_count() or 6
        default_threads = min(6, max_cpu)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, max_cpu)
        self.spin_threads.setValue(default_threads)
        self.spin_threads.setToolTip("Number of CPU threads for inference (recommended 6 for i7 physical cores)")
        form.addRow("CPU Threads:", self.spin_threads)

        layout.addLayout(form)

        # Checkboxes
        self.chk_vad = QCheckBox("Enable VAD filter (skips silent audio segments)")
        self.chk_vad.setChecked(True)
        layout.addWidget(self.chk_vad)

        self.chk_timestamps = QCheckBox("Include timestamps in .docx document")
        self.chk_timestamps.setChecked(True)
        layout.addWidget(self.chk_timestamps)

        # Custom Output Directory
        out_layout = QHBoxLayout()
        self.txt_output_dir = QLineEdit()
        self.txt_output_dir.setPlaceholderText("Default: Same directory as audio file")
        self.txt_output_dir.setReadOnly(True)
        out_layout.addWidget(self.txt_output_dir)

        self.btn_browse_dir = QPushButton("Browse...")
        self.btn_browse_dir.setMaximumHeight(26)
        out_layout.addWidget(self.btn_browse_dir)

        self.btn_clear_dir = QPushButton("Reset")
        self.btn_clear_dir.setMaximumHeight(26)
        out_layout.addWidget(self.btn_clear_dir)

        layout.addLayout(out_layout)

        # Connect signals
        self.combo_model.currentIndexChanged.connect(self._on_setting_changed)
        self.combo_lang.currentIndexChanged.connect(self._on_setting_changed)
        self.combo_device.currentIndexChanged.connect(self._on_device_changed)
        self.combo_compute.currentIndexChanged.connect(self._on_setting_changed)
        self.spin_threads.valueChanged.connect(self._on_setting_changed)
        self.chk_vad.toggled.connect(self._on_setting_changed)
        self.chk_timestamps.toggled.connect(self._on_setting_changed)

        self.btn_browse_dir.clicked.connect(self._choose_output_dir)
        self.btn_clear_dir.clicked.connect(self._reset_output_dir)

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
        )
