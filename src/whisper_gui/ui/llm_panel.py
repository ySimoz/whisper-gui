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
from whisper_gui.i18n import tr
from whisper_gui.llm_cleaner import (
    DEFAULT_INSTRUCTION_PROMPT,
    PROVIDER_PRESETS,
    load_instructions,
    normalize_model_name,
    test_llm_connection,
)
from whisper_gui.models import LLMConfig
from whisper_gui.ui.theme import ToggleSwitch, get_palette


class InstructionEditorDialog(QDialog):
    """Dialog to view and fine-tune the LLM markdown instructions."""

    def __init__(self, current_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("llm.editor_title"))
        self.resize(650, 480)
        self.modified_text = current_text

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(current_text)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(11)
        self.editor.setFont(font)
        layout.addWidget(self.editor)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = btn_box.button(QDialogButtonBox.Ok)
        cancel_btn = btn_box.button(QDialogButtonBox.Cancel)
        if ok_btn is not None:
            ok_btn.setText(tr("llm.editor_ok"))
        if cancel_btn is not None:
            cancel_btn.setText(tr("llm.editor_cancel"))
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
        self._conn_state: str | None = None  # "ok", "err", or None
        self._section_labels: list[QLabel] = []
        self._field_labels: list[QLabel] = []
        self._section_label_keys: list[tuple[QLabel, str]] = []
        self._field_label_keys: list[tuple[QLabel, str]] = []

        self._build_ui()
        self.apply_theme()
        self._on_provider_changed("DeepSeek")
        self._update_enabled_states()

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
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        sec_hdr = QLabel(tr("llm.sec_title"))
        self._section_labels.append(sec_hdr)
        self._section_label_keys.append((sec_hdr, "llm.sec_title"))
        main_layout.addWidget(sec_hdr)

        self.chk_enable = ToggleSwitch(tr("llm.chk_enable"))
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
        self.combo_provider = QComboBox()
        self.combo_provider.setView(QListView())
        for provider_id in ("DeepSeek", "Anthropic (Claude)", "OpenAI", "Groq", "Custom"):
            label = tr("llm.provider_custom") if provider_id == "Custom" else provider_id
            self.combo_provider.addItem(label, provider_id)
        self.combo_provider.setFixedHeight(36)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_index_changed)
        self._add_field_group(ctrl_layout, "llm.provider", self.combo_provider)

        # Model Name
        self.combo_model = QComboBox()
        self.combo_model.setView(QListView())
        self.combo_model.setEditable(True)
        self.combo_model.setFixedHeight(36)
        self.combo_model.currentTextChanged.connect(self._on_setting_changed)
        self._add_field_group(ctrl_layout, "llm.model_name", self.combo_model)

        # Base URL
        self.txt_base_url = QLineEdit()
        self.txt_base_url.setFixedHeight(36)
        self.txt_base_url.setPlaceholderText("https://api.deepseek.com/v1")
        self.txt_base_url.textChanged.connect(self._on_setting_changed)
        self._add_field_group(ctrl_layout, "llm.base_url", self.txt_base_url)

        # API Key
        key_box = QHBoxLayout()
        key_box.setSpacing(8)
        self.txt_api_key = QLineEdit()
        self.txt_api_key.setFixedHeight(36)
        self.txt_api_key.setEchoMode(QLineEdit.Password)
        self.txt_api_key.setPlaceholderText(tr("llm.api_key_placeholder"))
        self.txt_api_key.textChanged.connect(self._on_setting_changed)
        key_box.addWidget(self.txt_api_key, stretch=1)

        self.btn_toggle_key = QPushButton(tr("llm.show_btn"))
        self.btn_toggle_key.setFixedHeight(36)
        self.btn_toggle_key.setFixedWidth(76)
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        key_box.addWidget(self.btn_toggle_key)

        self.btn_test_conn = QPushButton(tr("llm.test_conn_btn"))
        self.btn_test_conn.setFixedHeight(36)
        self.btn_test_conn.clicked.connect(self._test_connection)
        key_box.addWidget(self.btn_test_conn)

        self.lbl_conn_status = QLabel("")
        self.lbl_conn_status.setWordWrap(True)
        self.lbl_conn_status.setStyleSheet("font-size: 12px;")

        key_group = QVBoxLayout()
        key_group.setContentsMargins(0, 0, 0, 0)
        key_group.setSpacing(4)
        key_group.addLayout(key_box)
        key_group.addWidget(self.lbl_conn_status)
        self._add_field_group(ctrl_layout, "llm.api_key", key_group)

        # Prompt Instructions
        self.lbl_active_prompt = QLabel(tr("llm.active_default"))

        prompt_btn_row = QHBoxLayout()
        prompt_btn_row.setSpacing(8)

        self.btn_view_edit = QPushButton(tr("llm.view_edit_btn"))
        self.btn_view_edit.setFixedHeight(32)
        self.btn_view_edit.clicked.connect(self._view_edit_instructions)
        prompt_btn_row.addWidget(self.btn_view_edit)

        self.btn_import_md = QPushButton(tr("llm.import_md_btn"))
        self.btn_import_md.setFixedHeight(32)
        self.btn_import_md.clicked.connect(self._import_md_file)
        prompt_btn_row.addWidget(self.btn_import_md)

        self.btn_reset_default = QPushButton(tr("llm.reset_default_btn"))
        self.btn_reset_default.setFixedHeight(32)
        self.btn_reset_default.clicked.connect(self._reset_instructions)
        prompt_btn_row.addWidget(self.btn_reset_default)

        prompt_btn_row.addStretch()

        prompt_group = QVBoxLayout()
        prompt_group.setContentsMargins(0, 0, 0, 0)
        prompt_group.setSpacing(8)
        prompt_group.addWidget(self.lbl_active_prompt)
        prompt_group.addLayout(prompt_btn_row)
        self._add_field_group(ctrl_layout, "llm.custom_prompt", prompt_group)

        self.chk_raw_appendix = ToggleSwitch(tr("llm.chk_raw_appendix"))
        self.chk_raw_appendix.setChecked(True)
        self.chk_raw_appendix.toggled.connect(self._on_setting_changed)
        ctrl_layout.addWidget(self.chk_raw_appendix)

        main_layout.addWidget(self.controls_container)
        main_layout.addStretch()

    def apply_theme(self) -> None:
        """Apply the active theme palette to LLM panel labels and status text."""
        p = get_palette()
        sec_style = f"color: {p.text_main}; font-size: 16px; font-weight: 500; padding: 0;"
        field_style = f"color: {p.text_secondary}; font-size: 13px; font-weight: 500; padding: 0;"
        for lbl in self._section_labels:
            lbl.setStyleSheet(sec_style)
        for lbl in self._field_labels:
            lbl.setStyleSheet(field_style)
        self.chk_enable.setStyleSheet(
            f"color: {p.text_main}; font-weight: 500; font-size: 13px; background-color: transparent;"
        )
        self.lbl_active_prompt.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self.chk_raw_appendix.setStyleSheet(
            f"color: {p.text_main}; font-size: 13px; background-color: transparent;"
        )
        if self._conn_state == "ok":
            self.lbl_conn_status.setStyleSheet(f"color: {p.positive}; font-weight: 500; font-size: 12px;")
        elif self._conn_state == "err":
            self.lbl_conn_status.setStyleSheet(f"color: {p.negative}; font-weight: 500; font-size: 12px;")
        else:
            self.lbl_conn_status.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self._update_enabled_states()

    def retranslate_ui(self) -> None:
        """Update all visible strings to the active application language."""
        for lbl, key in self._section_label_keys:
            lbl.setText(tr(key))
        for lbl, key in self._field_label_keys:
            lbl.setText(tr(key))
        self.chk_enable.setText(tr("llm.chk_enable"))

        self.combo_provider.blockSignals(True)
        for i in range(self.combo_provider.count()):
            if self.combo_provider.itemData(i) == "Custom":
                self.combo_provider.setItemText(i, tr("llm.provider_custom"))
        self.combo_provider.blockSignals(False)

        self.txt_api_key.setPlaceholderText(tr("llm.api_key_placeholder"))
        self.btn_toggle_key.setText(
            tr("llm.hide_btn") if self.txt_api_key.echoMode() == QLineEdit.Normal else tr("llm.show_btn")
        )
        self.btn_test_conn.setText(tr("llm.test_conn_btn"))
        self._refresh_active_prompt_label()
        self.btn_view_edit.setText(tr("llm.view_edit_btn"))
        self.btn_import_md.setText(tr("llm.import_md_btn"))
        self.btn_reset_default.setText(tr("llm.reset_default_btn"))
        self.chk_raw_appendix.setText(tr("llm.chk_raw_appendix"))
        self._update_enabled_states()

    def _refresh_active_prompt_label(self) -> None:
        if self._custom_instruction_path and self._custom_instruction_text is not None:
            if self._custom_instruction_path.is_file() and self._custom_instruction_text == self._custom_instruction_path.read_text(encoding="utf-8", errors="replace"):
                self.lbl_active_prompt.setText(tr("llm.active_file", name=self._custom_instruction_path.name))
            else:
                self.lbl_active_prompt.setText(tr("llm.active_custom_file", name=self._custom_instruction_path.name))
        elif self._custom_instruction_path and Path(self._custom_instruction_path).is_file():
            self.lbl_active_prompt.setText(tr("llm.active_file", name=Path(self._custom_instruction_path).name))
        elif self._custom_instruction_text:
            self.lbl_active_prompt.setText(tr("llm.active_custom_instructions"))
        else:
            self.lbl_active_prompt.setText(tr("llm.active_default"))

    def _on_provider_index_changed(self, _index: int) -> None:
        provider = str(self.combo_provider.currentData() or self.combo_provider.currentText())
        self._on_provider_changed(provider)

    def _on_toggle_enabled(self, checked: bool) -> None:
        self._update_enabled_states()
        self.config_changed.emit()

    def _update_enabled_states(self) -> None:
        # Configuration inputs remain active so the user can configure & test anytime.
        return

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
            self.btn_toggle_key.setText(tr("llm.hide_btn"))
        else:
            self.txt_api_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_key.setText(tr("llm.show_btn"))

    def _test_connection(self) -> None:
        cfg = self.get_config()
        p = get_palette()
        self._conn_state = None
        self.lbl_conn_status.setStyleSheet(f"color: {p.text_muted}; font-size: 12px;")
        self.lbl_conn_status.setText(tr("llm.connecting"))
        self.btn_test_conn.setEnabled(False)

        try:
            ok, msg = test_llm_connection(cfg, timeout=12.0)
            if ok:
                self._conn_state = "ok"
                self.lbl_conn_status.setStyleSheet(
                    f"color: {p.positive}; font-weight: 500; font-size: 12px;"
                )
                self.lbl_conn_status.setText(msg)
            else:
                self._conn_state = "err"
                self.lbl_conn_status.setStyleSheet(
                    f"color: {p.negative}; font-weight: 500; font-size: 12px;"
                )
                self.lbl_conn_status.setText(msg)
        finally:
            self.btn_test_conn.setEnabled(True)

    def _import_md_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("llm.import_title"),
            "",
            tr("llm.import_filter"),
        )
        if not file_path:
            return

        p = Path(file_path)
        try:
            content = p.read_text(encoding="utf-8")
            self._custom_instruction_path = p
            self._custom_instruction_text = content
            self.lbl_active_prompt.setText(tr("llm.active_file", name=p.name))
            self.config_changed.emit()
            QMessageBox.information(
                self,
                tr("llm.import_ok_title"),
                tr("llm.import_ok_body", name=p.name),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                tr("llm.import_err_title"),
                tr("llm.import_err_body", name=p.name, error=e),
            )

    def _view_edit_instructions(self) -> None:
        cfg = self.get_config()
        current_text, _ = load_instructions(cfg)
        dlg = InstructionEditorDialog(current_text, self)
        if dlg.exec() == QDialog.Accepted:
            self._custom_instruction_text = dlg.modified_text
            if self._custom_instruction_path:
                self.lbl_active_prompt.setText(
                    tr("llm.active_custom_file", name=self._custom_instruction_path.name)
                )
            else:
                self.lbl_active_prompt.setText(tr("llm.active_custom_prompt"))
            self.config_changed.emit()

    def _reset_instructions(self) -> None:
        self._custom_instruction_path = None
        self._custom_instruction_text = None
        self.lbl_active_prompt.setText(tr("llm.active_default"))
        self.config_changed.emit()

    def get_config(self) -> LLMConfig:
        raw_model = self.combo_model.currentText().strip() or "DeepSeek V4.1 Flash"
        provider = str(self.combo_provider.currentData() or self.combo_provider.currentText())
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
        idx = self.combo_provider.findData(cfg.provider)
        if idx < 0:
            idx = self.combo_provider.findText(cfg.provider)
        if idx >= 0:
            self.combo_provider.setCurrentIndex(idx)
        elif "claude" in cfg.provider.lower() or "anthropic" in cfg.provider.lower():
            idx = self.combo_provider.findData("Anthropic (Claude)")
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
                tr("llm.active_file", name=Path(cfg.instruction_file).name)
            )
        elif cfg.custom_instructions_text:
            self.lbl_active_prompt.setText(tr("llm.active_custom_instructions"))
        else:
            self.lbl_active_prompt.setText(tr("llm.active_default"))

        self._update_enabled_states()

    def save_settings(self, settings: QSettings) -> None:
        """Persist user LLM preferences and API key."""
        settings.beginGroup("LLM")
        settings.setValue("enabled", self.chk_enable.isChecked())
        settings.setValue("provider", str(self.combo_provider.currentData() or self.combo_provider.currentText()))
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
