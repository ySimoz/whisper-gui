"""Panel widget for configuring LLM transcript polishing and reformatting."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.llm_cleaner import (
    DEFAULT_INSTRUCTION_PROMPT,
    PROVIDER_PRESETS,
    load_instructions,
    normalize_model_name,
    test_llm_connection,
)
from whisper_gui.models import LLMConfig
from whisper_gui.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BORDER,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_SECONDARY_HOVER,
    COLOR_SECONDARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
)


class InstructionEditorDialog(QDialog):
    """Dialog to view and fine-tune the LLM markdown instructions."""

    def __init__(self, current_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Transcript Polishing Instructions")
        self.resize(650, 480)
        self.modified_text = current_text

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        hint_lbl = QLabel(
            "Instructions guide the LLM on how to reformat sentences, eliminate pauses, "
            "and clean up verbal fillers. Markdown format is supported."
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(hint_lbl)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_text)
        font = QFont("Monospace")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.editor.setFont(font)
        layout.addWidget(self.editor)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_accept(self) -> None:
        self.modified_text = self.editor.toPlainText()
        self.accept()


class LLMPanel(QWidget):
    """Clean, unbloated configuration panel for LLM speech refinement."""

    config_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._custom_instruction_path: Path | None = None
        self._custom_instruction_text: str | None = None

        self._build_ui()
        self._on_provider_changed("DeepSeek")
        self._update_enabled_states()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(8)

        # 1. Top Options Bar: Checkboxes
        top_bar = QFrame()
        top_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {COLOR_BG_INPUT};
                border: 1px solid {COLOR_BORDER};
                border-radius: 4px;
            }}
        """)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(16)

        self.chk_enable = QCheckBox("Enable Text Polishing (LLM)")
        font_chk = QFont()
        font_chk.setBold(True)
        font_chk.setPointSize(11)
        self.chk_enable.setFont(font_chk)
        self.chk_enable.setStyleSheet(f"color: {COLOR_SECONDARY}; font-weight: bold;")
        self.chk_enable.toggled.connect(self._on_toggle_enabled)
        top_layout.addWidget(self.chk_enable)

        self.chk_raw_appendix = QCheckBox("Include raw transcript in Word document")
        self.chk_raw_appendix.setChecked(True)
        self.chk_raw_appendix.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        self.chk_raw_appendix.toggled.connect(self._on_setting_changed)
        top_layout.addWidget(self.chk_raw_appendix)

        top_layout.addStretch()

        self.lbl_workflow_status = QLabel("")
        top_layout.addWidget(self.lbl_workflow_status)
        main_layout.addWidget(top_bar)

        # 2. Compact Settings Grid (ALWAYS interactive so users can configure & test anytime)
        self.controls_container = QWidget()
        grid = QGridLayout(self.controls_container)
        grid.setContentsMargins(4, 2, 4, 2)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        # Row 0: Provider & Model & Base URL
        grid.addWidget(QLabel("Provider:"), 0, 0)
        self.combo_provider = QComboBox()
        self.combo_provider.addItems(["DeepSeek", "OpenAI", "Groq", "Custom"])
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        grid.addWidget(self.combo_provider, 0, 1)

        grid.addWidget(QLabel("Model:"), 0, 2)
        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        self.combo_model.currentTextChanged.connect(self._on_setting_changed)
        grid.addWidget(self.combo_model, 0, 3)

        grid.addWidget(QLabel("Base URL:"), 0, 4)
        self.txt_base_url = QLineEdit()
        self.txt_base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.txt_base_url.textChanged.connect(self._on_setting_changed)
        grid.addWidget(self.txt_base_url, 0, 5)

        # Row 1: API Key & Connection Test
        grid.addWidget(QLabel("API Key:"), 1, 0)

        key_box = QHBoxLayout()
        key_box.setSpacing(6)
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        self.txt_api_key.setPlaceholderText("API key (stored locally on your device)")
        self.txt_api_key.textChanged.connect(self._on_setting_changed)
        key_box.addWidget(self.txt_api_key)

        self.btn_toggle_key = QPushButton("Show")
        self.btn_toggle_key.setFixedWidth(60)
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        key_box.addWidget(self.btn_toggle_key)

        self.btn_test_conn = QPushButton("Test Connection")
        self.btn_test_conn.setStyleSheet(f"""
            QPushButton {{
                background-color: #2D1A28;
                border: 1px solid {COLOR_SECONDARY};
                color: {COLOR_SECONDARY};
                font-weight: bold;
                padding: 4px 12px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {COLOR_SECONDARY};
                color: {COLOR_SECONDARY_TEXT};
            }}
        """)
        self.btn_test_conn.clicked.connect(self._test_connection)
        key_box.addWidget(self.btn_test_conn)

        grid.addLayout(key_box, 1, 1, 1, 5)

        # Row 2: Prompt Instructions & Import / Edit
        grid.addWidget(QLabel("Instructions:"), 2, 0)

        prompt_box = QHBoxLayout()
        prompt_box.setSpacing(6)

        self.lbl_active_prompt = QLabel("Active: Default (Speech Polisher)")
        self.lbl_active_prompt.setStyleSheet(f"color: {COLOR_TEXT_MAIN}; font-size: 11px;")
        prompt_box.addWidget(self.lbl_active_prompt)

        prompt_box.addStretch()

        self.btn_import_md = QPushButton("Import File...")
        self.btn_import_md.clicked.connect(self._import_md_file)
        prompt_box.addWidget(self.btn_import_md)

        self.btn_view_edit = QPushButton("View / Edit")
        self.btn_view_edit.clicked.connect(self._view_edit_instructions)
        prompt_box.addWidget(self.btn_view_edit)

        self.btn_reset_default = QPushButton("Reset to Default")
        self.btn_reset_default.clicked.connect(self._reset_instructions)
        prompt_box.addWidget(self.btn_reset_default)

        grid.addLayout(prompt_box, 2, 1, 1, 5)

        # Row 3: Status / Feedback message
        self.lbl_conn_status = QLabel("")
        self.lbl_conn_status.setWordWrap(True)
        self.lbl_conn_status.setStyleSheet("font-size: 11px;")
        grid.addWidget(self.lbl_conn_status, 3, 1, 1, 5)

        main_layout.addWidget(self.controls_container)
        main_layout.addStretch()

    def _on_toggle_enabled(self, checked: bool) -> None:
        self._update_enabled_states()
        self.config_changed.emit()

    def _update_enabled_states(self) -> None:
        # Crucial UX fix: All configuration inputs remain active so the user can
        # paste their API key, select models, and test connections at any time.
        enabled = self.chk_enable.isChecked()
        if hasattr(self, "lbl_workflow_status"):
            if enabled:
                self.lbl_workflow_status.setText("Enabled for transcriptions")
                self.lbl_workflow_status.setStyleSheet(
                    f"color: {COLOR_SECONDARY}; font-weight: bold; font-size: 11px;"
                )
            else:
                self.lbl_workflow_status.setText("Disabled (configure & test anytime)")
                self.lbl_workflow_status.setStyleSheet(
                    f"color: {COLOR_TEXT_MUTED}; font-size: 11px;"
                )

    def _on_provider_changed(self, provider: str) -> None:
        preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["DeepSeek"])
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        if preset["models"]:
            self.combo_model.addItems(preset["models"])
            idx = self.combo_model.findText(preset["default_model"])
            if idx >= 0:
                self.combo_model.setCurrentIndex(idx)
            else:
                self.combo_model.setCurrentText(preset["default_model"])
        else:
            self.combo_model.setEditText(preset["default_model"])
        self.combo_model.blockSignals(False)

        self.txt_base_url.setText(preset["base_url"])
        self.lbl_conn_status.setText("")
        self.config_changed.emit()

    def _on_setting_changed(self) -> None:
        self.lbl_conn_status.setText("")
        self.config_changed.emit()

    def _toggle_key_visibility(self) -> None:
        if self.txt_api_key.echoMode() == QLineEdit.Password:
            self.txt_api_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_key.setText("Hide")
        else:
            self.txt_api_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_key.setText("Show")

    def _test_connection(self) -> None:
        cfg = self.get_config()
        self.lbl_conn_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        self.lbl_conn_status.setText("Connecting to LLM API...")
        self.btn_test_conn.setEnabled(False)

        try:
            ok, msg = test_llm_connection(cfg, timeout=12.0)
            if ok:
                self.lbl_conn_status.setStyleSheet(
                    f"color: {COLOR_PRIMARY}; font-weight: bold; font-size: 11px;"
                )
                self.lbl_conn_status.setText(msg)
            else:
                self.lbl_conn_status.setStyleSheet(
                    f"color: {COLOR_SECONDARY}; font-weight: bold; font-size: 11px;"
                )
                self.lbl_conn_status.setText(msg)
        finally:
            self.btn_test_conn.setEnabled(True)

    def _import_md_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Markdown Instruction File",
            "",
            "Markdown Files (*.md *.markdown *.txt);;All Files (*)",
        )
        if not file_path:
            return

        p = Path(file_path)
        try:
            content = p.read_text(encoding="utf-8")
            self._custom_instruction_path = p
            self._custom_instruction_text = content
            self.lbl_active_prompt.setText(f"Active: File: {p.name}")
            self.config_changed.emit()
            QMessageBox.information(
                self,
                "Instructions Loaded",
                f"Successfully loaded polishing instructions from '{p.name}'.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Loading File",
                f"Failed to read file '{p.name}':\n{e}",
            )

    def _view_edit_instructions(self) -> None:
        cfg = self.get_config()
        current_text, _ = load_instructions(cfg)
        dlg = InstructionEditorDialog(current_text, self)
        if dlg.exec() == QDialog.Accepted:
            self._custom_instruction_text = dlg.modified_text
            name = (
                f"Custom ({self._custom_instruction_path.name})"
                if self._custom_instruction_path
                else "Custom Prompt"
            )
            self.lbl_active_prompt.setText(f"Active: {name}")
            self.config_changed.emit()

    def _reset_instructions(self) -> None:
        self._custom_instruction_path = None
        self._custom_instruction_text = None
        self.lbl_active_prompt.setText("Active: Default (Speech Polisher)")
        self.config_changed.emit()

    def get_config(self) -> LLMConfig:
        raw_model = self.combo_model.currentText().strip() or "DeepSeek V4.1 Flash"
        provider = self.combo_provider.currentText()
        normalized_model = normalize_model_name(provider, raw_model)
        return LLMConfig(
            enabled=self.chk_enable.isChecked(),
            provider=provider,
            model_name=normalized_model,
            api_key=self.txt_api_key.text().strip(),
            base_url=self.txt_base_url.text().strip() or "https://api.deepseek.com/v1",
            instruction_file=self._custom_instruction_path,
            custom_instructions_text=self._custom_instruction_text,
            include_raw_in_docx=self.chk_raw_appendix.isChecked(),
        )

    def set_config(self, cfg: LLMConfig) -> None:
        self.chk_enable.setChecked(cfg.enabled)
        idx = self.combo_provider.findText(cfg.provider)
        if idx >= 0:
            self.combo_provider.setCurrentIndex(idx)

        # Match model name in combo box with smart alias resolution
        target = cfg.model_name
        matched_idx = self.combo_model.findText(target, Qt.MatchFixedString)
        if matched_idx < 0 and cfg.provider == "DeepSeek":
            norm = normalize_model_name(cfg.provider, target)
            if norm == "deepseek-flash":
                matched_idx = self.combo_model.findText("DeepSeek V4.1 Flash")
            elif norm == "deepseek-v4-pro":
                matched_idx = self.combo_model.findText("DeepSeek V4 Pro")

        if matched_idx >= 0:
            self.combo_model.setCurrentIndex(matched_idx)
        else:
            self.combo_model.setCurrentText(target)

        self.txt_api_key.setText(cfg.api_key)
        self.txt_base_url.setText(cfg.base_url)
        self.chk_raw_appendix.setChecked(cfg.include_raw_in_docx)

        self._custom_instruction_path = cfg.instruction_file
        self._custom_instruction_text = cfg.custom_instructions_text
        if cfg.instruction_file and Path(cfg.instruction_file).is_file():
            self.lbl_active_prompt.setText(
                f"Active: File: {Path(cfg.instruction_file).name}"
            )
        elif cfg.custom_instructions_text:
            self.lbl_active_prompt.setText("Active: Custom Instructions")
        else:
            self.lbl_active_prompt.setText("Active: Default (Speech Polisher)")

        self._update_enabled_states()

    def save_settings(self, settings: QSettings) -> None:
        """Persist user LLM preferences and API key."""
        settings.beginGroup("LLM")
        settings.setValue("enabled", self.chk_enable.isChecked())
        settings.setValue("provider", self.combo_provider.currentText())
        settings.setValue("model_name", self.combo_model.currentText())
        settings.setValue("api_key", self.txt_api_key.text().strip())
        settings.setValue("base_url", self.txt_base_url.text().strip())
        settings.setValue("include_raw_docx", self.chk_raw_appendix.isChecked())
        if self._custom_instruction_path:
            settings.setValue("instruction_file", str(self._custom_instruction_path))
        else:
            settings.setValue("instruction_file", "")
        settings.endGroup()

    def load_settings(self, settings: QSettings) -> None:
        """Load user LLM preferences."""
        settings.beginGroup("LLM")
        enabled = settings.value("enabled", False, type=bool)
        provider = settings.value("provider", "DeepSeek", type=str)
        model = settings.value("model_name", "DeepSeek V4.1 Flash", type=str)
        api_key = settings.value("api_key", "", type=str)
        base_url = settings.value("base_url", "https://api.deepseek.com/v1", type=str)
        include_raw = settings.value("include_raw_docx", True, type=bool)
        instr_path_str = settings.value("instruction_file", "", type=str)
        settings.endGroup()

        instr_file = Path(instr_path_str) if instr_path_str and Path(instr_path_str).is_file() else None

        cfg = LLMConfig(
            enabled=enabled,
            provider=provider,
            model_name=model,
            api_key=api_key,
            base_url=base_url,
            instruction_file=instr_file,
            include_raw_in_docx=include_raw,
        )
        self.set_config(cfg)
