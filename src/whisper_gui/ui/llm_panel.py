"""Panel widget for configuring LLM transcript polishing and reformatting."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
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
    QListView,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from whisper_gui.credentials import load_api_key, store_api_key
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
    COLOR_NEGATIVE,
    COLOR_POSITIVE,
    COLOR_PRIMARY,
    COLOR_PRIMARY_HOVER,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY,
    COLOR_SECONDARY_HOVER,
    COLOR_SECONDARY_TEXT,
    COLOR_TEXT_HINT,
    COLOR_TEXT_MAIN,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
)

_SECTION_LABEL_STYLE = f"color: {COLOR_TEXT_MAIN}; font-size: 16px; font-weight: 500; padding: 0;"
_FIELD_LABEL_STYLE = f"color: {COLOR_TEXT_SECONDARY}; font-size: 13px; font-weight: 500; padding: 0;"


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

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_text)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(11)
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
        self.setObjectName("llm_panel")
        self.setStyleSheet("#llm_panel { background-color: transparent; }")
        self._custom_instruction_path: Path | None = None
        self._custom_instruction_text: str | None = None

        self._build_ui()
        self._on_provider_changed("DeepSeek")
        self._update_enabled_states()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        sec_hdr = QLabel("Transcript Polishing")
        sec_hdr.setStyleSheet(_SECTION_LABEL_STYLE)
        main_layout.addWidget(sec_hdr)

        self.chk_enable = QCheckBox("Enable transcript polishing")
        self.chk_enable.setStyleSheet(f"color: {COLOR_TEXT_MAIN}; font-weight: 500; font-size: 13px; background-color: transparent;")
        self.chk_enable.toggled.connect(self._on_toggle_enabled)
        main_layout.addWidget(self.chk_enable)

        # Controls container
        self.controls_container = QWidget()
        self.controls_container.setObjectName("llm_controls_container")
        self.controls_container.setStyleSheet("#llm_controls_container { background-color: transparent; }")
        ctrl_layout = QVBoxLayout(self.controls_container)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(12)

        # Provider
        lbl_prov = QLabel("Provider")
        lbl_prov.setStyleSheet(_FIELD_LABEL_STYLE)
        ctrl_layout.addWidget(lbl_prov)

        self.combo_provider = QComboBox()
        self.combo_provider.setView(QListView())
        self.combo_provider.addItems(["DeepSeek", "Anthropic (Claude)", "OpenAI", "Groq", "Custom"])
        self.combo_provider.setFixedHeight(36)
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        ctrl_layout.addWidget(self.combo_provider)

        # Model Name
        lbl_mod = QLabel("Model Name")
        lbl_mod.setStyleSheet(_FIELD_LABEL_STYLE)
        ctrl_layout.addWidget(lbl_mod)

        self.combo_model = QComboBox()
        self.combo_model.setView(QListView())
        self.combo_model.setEditable(True)
        self.combo_model.setFixedHeight(36)
        self.combo_model.currentTextChanged.connect(self._on_setting_changed)
        ctrl_layout.addWidget(self.combo_model)

        # Base URL
        lbl_url = QLabel("API Base URL")
        lbl_url.setStyleSheet(_FIELD_LABEL_STYLE)
        ctrl_layout.addWidget(lbl_url)

        self.txt_base_url = QLineEdit()
        self.txt_base_url.setFixedHeight(36)
        self.txt_base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.txt_base_url.textChanged.connect(self._on_setting_changed)
        ctrl_layout.addWidget(self.txt_base_url)

        # API Key
        lbl_key = QLabel("API Key")
        lbl_key.setStyleSheet(_FIELD_LABEL_STYLE)
        ctrl_layout.addWidget(lbl_key)

        key_box = QHBoxLayout()
        key_box.setSpacing(8)
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setFixedHeight(36)
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        self.txt_api_key.setPlaceholderText("Paste API key")
        self.txt_api_key.textChanged.connect(self._on_setting_changed)
        key_box.addWidget(self.txt_api_key, stretch=1)

        self.btn_toggle_key = QPushButton("Show")
        self.btn_toggle_key.setFixedHeight(36)
        self.btn_toggle_key.setFixedWidth(64)
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        key_box.addWidget(self.btn_toggle_key)

        self.btn_test_conn = QPushButton("Test Connection")
        self.btn_test_conn.setFixedHeight(36)
        self.btn_test_conn.clicked.connect(self._test_connection)
        key_box.addWidget(self.btn_test_conn)
        ctrl_layout.addLayout(key_box)

        self.lbl_conn_status = QLabel("")
        self.lbl_conn_status.setWordWrap(True)
        self.lbl_conn_status.setStyleSheet("font-size: 12px;")
        ctrl_layout.addWidget(self.lbl_conn_status)

        # Prompt Instructions
        lbl_prompt = QLabel("Custom Instructions Prompt")
        lbl_prompt.setStyleSheet(_FIELD_LABEL_STYLE)
        ctrl_layout.addWidget(lbl_prompt)

        self.lbl_active_prompt = QLabel("Active: Default (Speech Polisher)")
        self.lbl_active_prompt.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px;")
        ctrl_layout.addWidget(self.lbl_active_prompt)

        prompt_btn_row = QHBoxLayout()
        prompt_btn_row.setSpacing(8)

        self.btn_view_edit = QPushButton("View / Edit Prompt")
        self.btn_view_edit.setFixedHeight(32)
        self.btn_view_edit.clicked.connect(self._view_edit_instructions)
        prompt_btn_row.addWidget(self.btn_view_edit)

        self.btn_import_md = QPushButton("Import .md File")
        self.btn_import_md.setFixedHeight(32)
        self.btn_import_md.clicked.connect(self._import_md_file)
        prompt_btn_row.addWidget(self.btn_import_md)

        self.btn_reset_default = QPushButton("Reset to Default")
        self.btn_reset_default.setFixedHeight(32)
        self.btn_reset_default.clicked.connect(self._reset_instructions)
        prompt_btn_row.addWidget(self.btn_reset_default)

        prompt_btn_row.addStretch()
        ctrl_layout.addLayout(prompt_btn_row)

        self.chk_raw_appendix = QCheckBox("Include raw transcript in Word document")
        self.chk_raw_appendix.setChecked(True)
        self.chk_raw_appendix.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 12px; background-color: transparent;")
        self.chk_raw_appendix.toggled.connect(self._on_setting_changed)
        ctrl_layout.addWidget(self.chk_raw_appendix)

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
        self.txt_base_url.setPlaceholderText(preset["base_url"])
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
                    f"color: {COLOR_POSITIVE}; font-weight: 500; font-size: 12px;"
                )
                self.lbl_conn_status.setText(msg)
            else:
                self.lbl_conn_status.setStyleSheet(
                    f"color: {COLOR_NEGATIVE}; font-weight: 500; font-size: 12px;"
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
        elif "claude" in cfg.provider.lower() or "anthropic" in cfg.provider.lower():
            idx = self.combo_provider.findText("Anthropic (Claude)")
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
        elif matched_idx < 0 and ("anthropic" in cfg.provider.lower() or "claude" in cfg.provider.lower()):
            norm = normalize_model_name(cfg.provider, target)
            matched_idx = self.combo_model.findText(norm, Qt.MatchFixedString)

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
        settings.setValue("base_url", self.txt_base_url.text().strip())
        settings.setValue("include_raw_docx", self.chk_raw_appendix.isChecked())
        if self._custom_instruction_path:
            settings.setValue("instruction_file", str(self._custom_instruction_path))
        else:
            settings.setValue("instruction_file", "")
        settings.endGroup()
        store_api_key(self.txt_api_key.text().strip(), settings)

    def load_settings(self, settings: QSettings) -> None:
        """Load user LLM preferences."""
        settings.beginGroup("LLM")
        enabled = settings.value("enabled", False, type=bool)
        provider = settings.value("provider", "DeepSeek", type=str)
        model = settings.value("model_name", "DeepSeek V4.1 Flash", type=str)
        base_url = settings.value("base_url", "https://api.deepseek.com/v1", type=str)
        include_raw = settings.value("include_raw_docx", True, type=bool)
        instr_path_str = settings.value("instruction_file", "", type=str)
        settings.endGroup()
        api_key = load_api_key(settings)

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
