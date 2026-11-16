"""Tests for English/Italian localization, key parity, live UI switching, and exports."""

import ast
import string
from pathlib import Path

from docx import Document
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from whisper_gui.docx_exporter import export_transcript_to_docx
from whisper_gui.exporters import export_transcript_to_md, export_transcript_to_pdf, export_transcript_to_txt
from whisper_gui.i18n import (
    SUPPORTED_APP_LANGUAGES,
    TRANSLATIONS,
    display_track_status,
    get_language,
    set_language,
    tr,
)
from whisper_gui.models import (
    AudioInfo,
    SliceConfig,
    TrackStatus,
    TranscriptSegment,
    TranscriptionConfig,
    TranscriptionResult,
)
from whisper_gui.ui.main_window import MainWindow


def _get_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _extract_placeholders(template: str) -> set[str]:
    formatter = string.Formatter()
    return {field_name for _, field_name, _, _ in formatter.parse(template) if field_name is not None}


def test_translations_have_exact_key_and_placeholder_parity() -> None:
    en = TRANSLATIONS["en"]
    it = TRANSLATIONS["it"]
    assert set(en.keys()) == set(it.keys())
    assert {code for code, _ in SUPPORTED_APP_LANGUAGES} == {"en", "it"}

    for key in en:
        assert isinstance(en[key], str) and en[key].strip(), f"Empty English translation for {key}"
        assert isinstance(it[key], str) and it[key].strip(), f"Empty Italian translation for {key}"
        assert _extract_placeholders(en[key]) == _extract_placeholders(it[key]), (
            f"Placeholder mismatch for key '{key}'"
        )


def test_all_source_tr_keys_exist_in_both_languages() -> None:
    src_root = Path(__file__).resolve().parent.parent / "src" / "whisper_gui"
    referenced_keys: dict[str, list[str]] = {}

    for py_file in src_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                key = node.args[0].value
                referenced_keys.setdefault(key, []).append(f"{py_file.name}:{node.lineno}")

    assert referenced_keys, "Expected tr(...) calls in src/whisper_gui"
    missing_en = {k: v for k, v in referenced_keys.items() if k not in TRANSLATIONS["en"]}
    missing_it = {k: v for k, v in referenced_keys.items() if k not in TRANSLATIONS["it"]}
    assert not missing_en, f"Missing English keys: {missing_en}"
    assert not missing_it, f"Missing Italian keys: {missing_it}"


def test_set_language_and_track_status_translation() -> None:
    prev = get_language()
    try:
        assert set_language("it") == "it"
        assert tr("main.settings_button") == "Impostazioni"
        assert display_track_status("Ready", TrackStatus.QUEUED) == "Pronto"
        assert display_track_status("Queued", TrackStatus.QUEUED) == "In coda"
        assert display_track_status("Completed (2.5x real-time)", TrackStatus.COMPLETED) == (
            "Completed (2.5x real-time)"
        )

        # Unsupported language falls back safely to default English
        assert set_language("fr") == "en"
        assert tr("main.settings_button") == "Settings"
    finally:
        set_language(prev)


def test_main_window_live_language_switch_and_persistence(tmp_path: Path) -> None:
    _get_app()
    prev = get_language()
    settings_file = tmp_path / "test_settings.ini"
    qsettings = QSettings(str(settings_file), QSettings.Format.IniFormat)

    try:
        set_language("en")
        window = MainWindow()
        try:
            assert window.btn_open_settings.text() == "Settings"
            assert window.btn_start.text() == "Transcribe Audio"
            assert window.settings_page.btn_back.text() == "Back to Transcribe"
            assert window.llm_panel.btn_test_conn.text() == "Test Connection"
            assert window.transcript_view.btn_export.text() == "Export"
            assert window.transcript_view.btn_play_pause.text() == "Play"

            # Switch live to Italian via the settings combobox
            it_idx = window.settings_panel.combo_app_language.findData("it")
            assert it_idx >= 0
            window.settings_panel.combo_app_language.setCurrentIndex(it_idx)

            assert get_language() == "it"
            assert window.btn_open_settings.text() == "Impostazioni"
            assert window.btn_start.text() == "Trascrivi audio"
            assert window.settings_page.btn_back.text() == "Torna alla trascrizione"
            assert window.llm_panel.btn_test_conn.text() == "Verifica connessione"
            assert window.transcript_view.btn_export.text() == "Esporta"
            assert window.transcript_view.btn_play_pause.text() == "Riproduci"
            assert window.track_list.table.horizontalHeaderItem(0).text() == "Traccia"
            assert window.range_selector.radio_full.text() == "Audio completo"

            # Save and reload into a fresh SettingsPanel via isolated QSettings
            window.settings_panel.save_settings(qsettings)
            qsettings.sync()
            window.settings_panel.load_settings(qsettings)
            assert window.settings_panel.combo_app_language.currentData() == "it"

            # Switch live back to English
            en_idx = window.settings_panel.combo_app_language.findData("en")
            assert en_idx >= 0
            window.settings_panel.combo_app_language.setCurrentIndex(en_idx)

            assert get_language() == "en"
            assert window.btn_open_settings.text() == "Settings"
            assert window.btn_start.text() == "Transcribe Audio"
        finally:
            window.close()
    finally:
        set_language(prev)


def test_exports_are_localized_in_italian(tmp_path: Path) -> None:
    _get_app()
    prev = get_language()
    track_info = AudioInfo(
        path=tmp_path / "meeting.wav",
        filename="meeting.wav",
        duration=45.0,
        size_bytes=1_258_291,
    )
    slice_cfg = SliceConfig()
    config = TranscriptionConfig(model_name="small", language="it")
    result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Ciao mondo.")],
        full_text="Ciao mondo.",
        detected_language="it",
        language_probability=0.98,
        audio_duration=45.0,
        elapsed_time=3.0,
    )

    try:
        set_language("it")

        docx_path = export_transcript_to_docx(tmp_path / "out.docx", track_info, slice_cfg, config, result)
        doc = Document(str(docx_path))
        paragraphs_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Trascrizione Audio" in paragraphs_text
        assert "Trascrizione" in paragraphs_text

        txt_path = export_transcript_to_txt(tmp_path / "out.txt", track_info, slice_cfg, config, result)
        txt_content = txt_path.read_text(encoding="utf-8")
        assert "TRASCRIZIONE AUDIO" in txt_content
        assert "File sorgente:" in txt_content

        md_path = export_transcript_to_md(tmp_path / "out.md", track_info, slice_cfg, config, result)
        md_content = md_path.read_text(encoding="utf-8")
        assert "# Trascrizione Audio" in md_content
        assert "| Proprietà | Dettagli |" in md_content

        pdf_path = export_transcript_to_pdf(tmp_path / "out.pdf", track_info, slice_cfg, config, result)
        assert pdf_path.exists() and pdf_path.stat().st_size > 0
    finally:
        set_language(prev)
