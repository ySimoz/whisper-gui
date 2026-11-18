"""GUI widget and window tests using pytest-qt."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

# Ensure headless offscreen platform for test runner
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whisper_gui.audio_utils import get_ffmpeg_cmd
from whisper_gui.models import (
    AudioInfo,
    AudioTrack,
    SliceConfig,
    SliceMode,
    TrackStatus,
    TranscriptionConfig,
    TranscriptionResult,
    TranscriptSegment,
)
from whisper_gui.ui.main_window import MainWindow
from whisper_gui.ui.range_selector import RangeSelectorWidget, TrimAudioDialog
from whisper_gui.ui.settings_panel import SettingsPanel
from whisper_gui.ui.track_list_widget import TrackListWidget
from whisper_gui.ui.transcript_view import TranscriptView


@pytest.fixture
def dummy_track() -> AudioTrack:
    info = AudioInfo(
        path=Path("/tmp/speech.wav"),
        filename="speech.wav",
        duration=1200.0,  # 20 minutes
    )
    return AudioTrack("/tmp/speech.wav", info)


def test_range_selector_widget(qtbot, dummy_track):
    widget = RangeSelectorWidget()
    qtbot.addWidget(widget)

    # Initial state (no track)
    assert not widget.isEnabled()

    # Set track
    widget.set_track(dummy_track)
    assert widget.isEnabled()
    assert widget.radio_full.isChecked()
    assert "Full Audio" in widget.lbl_selected_length.text()

    # Switch to custom range and adjust end time
    widget.radio_custom.setChecked(True)
    assert widget.radio_custom.isChecked()
    assert dummy_track.slice_config.mode == SliceMode.RANGE

    from PySide6.QtCore import QTime
    widget.time_end.setTime(QTime(0, 5, 0))
    widget._on_time_changed()
    assert dummy_track.slice_config.start_sec == 0.0
    assert dummy_track.slice_config.effective_end(1200.0) == 300.0
    assert "05:00" in widget.lbl_selected_length.text()


def test_settings_panel(qtbot, tmp_path):
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    cfg = panel.get_config()
    assert cfg.model_name == "large-v3-turbo"
    assert cfg.device == "cpu"
    assert cfg.compute_type == "int8"
    assert cfg.vad_filter is True
    assert cfg.include_timestamps_in_docx is True

    # Change to tiny model
    idx_tiny = panel.combo_model.findData("tiny")
    panel.combo_model.setCurrentIndex(idx_tiny)
    cfg2 = panel.get_config()
    assert cfg2.model_name == "tiny"

    # Set custom output dir
    panel._custom_output_dir = tmp_path
    cfg3 = panel.get_config()
    assert cfg3.output_dir == tmp_path

    # Test export format & auto-export settings
    assert cfg.export_format == "docx"
    assert cfg.auto_export is True
    assert [panel.combo_export_format.itemData(i) for i in range(panel.combo_export_format.count())] == [
        "docx",
        "pdf",
        "md",
        "txt",
        "srt",
        "vtt",
    ]
    panel.combo_export_format.setCurrentIndex(1)  # pdf
    panel.chk_auto_export.setChecked(False)
    cfg4 = panel.get_config()
    assert cfg4.export_format == "pdf"
    assert cfg4.auto_export is False


def test_transcript_view(qtbot, tmp_path):
    view = TranscriptView()
    qtbot.addWidget(view)

    # Initially empty and buttons disabled
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_open_docx.isEnabled()
    assert not view.btn_view_polished.isEnabled()

    # Append segment
    seg = TranscriptSegment(start=2.0, end=5.5, text="Hello Whisper")
    view.append_segment(seg)
    assert "Hello Whisper" in view.txt_display.toPlainText()

    # Set polished text
    view.set_polished_text("Hello Whisper, polished and refined.", "deepseek-v4.1-flash")
    assert view.btn_view_polished.isEnabled()
    assert view.btn_view_polished.isChecked()
    assert view.txt_display.toPlainText() == "Hello Whisper, polished and refined."

    # Switch back to raw
    view.btn_view_raw.click()
    assert "Hello Whisper" in view.txt_display.toPlainText()

    # Update progress
    view.set_progress(50, "50% done")
    assert view.progress_bar.value() == 50

    # Mark completed docx and test export actions
    fake_docx = tmp_path / "result.docx"
    fake_docx.touch()
    view.set_completed_docx(fake_docx)
    assert view.btn_open_docx.isEnabled()
    assert view.btn_export.isEnabled()
    assert view.btn_open_folder.isEnabled()
    assert view.export_menu is not None
    menu_texts = [a.text() for a in view.export_menu.actions() if not a.isSeparator()]
    assert menu_texts == [
        "Word (.docx)",
        "PDF (.pdf)",
        "Markdown (.md)",
        "Plain Text (.txt)",
        "Subtitles (.srt)",
        "WebVTT (.vtt)",
        "Open Output Folder",
    ]

    # Test export triggers
    view._on_export_format("txt")
    txt_export = tmp_path / "result.txt"
    assert txt_export.exists()

    # Test clear confirmation prompt
    view.txt_display.setPlainText("Some transcription text")
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.No):
        view._on_clear_clicked()
    assert view.txt_display.toPlainText() == "Some transcription text"

    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
        view._on_clear_clicked()
    assert view.txt_display.toPlainText() == ""

    # Clear view
    view.clear_view()
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_open_docx.isEnabled()
    assert not view.btn_export.isEnabled()
    assert not view.btn_view_polished.isEnabled()


def test_track_list_widget(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFrame

    # Create sample wav files
    sample_file = tmp_path / "test_track.wav"
    cmd = [get_ffmpeg_cmd(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(sample_file)]
    subprocess.run(cmd, check=True, capture_output=True)
    second_file = tmp_path / "second_track.wav"
    subprocess.run([get_ffmpeg_cmd(), "-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=2", str(second_file)], check=True, capture_output=True)

    widget = TrackListWidget()
    qtbot.addWidget(widget)
    widget.show()

    # Toolbar: no Remove button, no '+' icons/prefixes on Add buttons, Clear disabled when empty
    assert not hasattr(widget, "btn_remove")
    assert widget.btn_add_files.icon().isNull()
    assert widget.btn_add_folder.icon().isNull()
    assert "+" not in widget.btn_add_files.text()
    assert "+" not in widget.btn_add_folder.text()
    assert not widget.btn_clear.isEnabled()
    assert widget.table.frameShape() == QFrame.Shape.NoFrame
    assert widget.table.horizontalHeader().isHidden()
    assert widget.table.isColumnHidden(1)
    assert widget.table.isColumnHidden(2)
    assert widget.table.isColumnHidden(3)
    assert widget.build_context_menu(0) is None
    assert len(widget.get_tracks()) == 0

    # Add files
    widget.add_audio_files([sample_file, second_file])
    tracks = widget.get_tracks()
    assert len(tracks) == 2
    assert widget.btn_clear.isEnabled()
    assert tracks[0].info.filename == "test_track.wav"
    assert widget.table.rowCount() == 2
    assert widget.get_track(tracks[0].id) == tracks[0]
    assert widget.get_track("nonexistent_id") is None

    # Context menu offers Rename and Remove cleanly
    menu = widget.build_context_menu(0)
    assert menu is not None
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    action_texts = [a.text() for a in menu.actions()]
    assert action_texts == ["Rename", "Remove"]

    # Rename via action (and verify cancel/blank leaves filename unchanged)
    renamed_tracks = []
    widget.track_renamed.connect(renamed_tracks.append)
    with patch.object(widget, "_prompt_track_name", return_value=("", True)):
        assert not widget._rename_track_at(0)
        assert widget.get_tracks()[0].info.filename == "test_track.wav"
    with patch.object(widget, "_prompt_track_name", return_value=("Interview Take 1", False)):
        assert not widget._rename_track_at(0)
    with patch.object(widget, "_prompt_track_name", return_value=("Interview Take 1", True)):
        menu.actions()[0].trigger()
    assert widget.get_tracks()[0].info.filename == "Interview Take 1"
    assert widget.get_tracks()[0].file_path == sample_file.resolve()
    assert widget.table.item(0, 0).text() == "Interview Take 1"
    assert len(renamed_tracks) == 1

    # Remove via context menu action removes only target track
    menu.actions()[1].trigger()
    assert len(widget.get_tracks()) == 1
    assert widget.get_tracks()[0].info.filename == "second_track.wav"

    # Clear
    widget.clear_all()
    assert len(widget.get_tracks()) == 0
    assert widget.table.rowCount() == 0
    assert not widget.btn_clear.isEnabled()


def test_llm_panel(qtbot, tmp_path, monkeypatch):
    from whisper_gui.ui.llm_panel import LLMPanel
    from whisper_gui.models import LLMConfig
    from PySide6.QtCore import QSettings

    # Isolate credential backend from host OS keychain during tests
    monkeypatch.setattr("whisper_gui.credentials.sys.platform", "linux")
    monkeypatch.setattr("whisper_gui.credentials.shutil.which", lambda _name: None)

    panel = LLMPanel()
    qtbot.addWidget(panel)

    # Initial state: controls are ALWAYS interactive, toggle governs transcription only
    assert not panel.chk_enable.isChecked()
    assert panel.controls_container.isEnabled()
    assert panel.combo_model.currentText() == "DeepSeek V4.1 Flash"
    cfg = panel.get_config()
    assert cfg.enabled is False
    assert cfg.model_name == "deepseek-flash"
    assert cfg.provider == "DeepSeek"

    # Select DeepSeek V4 Pro
    panel.combo_model.setCurrentText("DeepSeek V4 Pro")
    assert panel.get_config().model_name == "deepseek-v4-pro"

    # Toggle enable
    panel.chk_enable.setChecked(True)
    assert panel.controls_container.isEnabled()
    assert panel.get_config().enabled is True

    # Switch provider to Anthropic (Claude)
    panel.combo_provider.setCurrentText("Anthropic (Claude)")
    cfg_claude = panel.get_config()
    assert cfg_claude.provider == "Anthropic (Claude)"
    assert cfg_claude.model_name == "claude-3-7-sonnet-20250219"
    assert "api.anthropic.com" in cfg_claude.base_url

    # Switch provider to OpenAI
    panel.combo_provider.setCurrentText("OpenAI")
    cfg_openai = panel.get_config()
    assert cfg_openai.provider == "OpenAI"
    assert cfg_openai.model_name == "gpt-4o-mini"
    assert "api.openai.com" in cfg_openai.base_url

    # Switch back to DeepSeek
    panel.combo_provider.setCurrentText("DeepSeek")
    cfg_ds = panel.get_config()
    assert cfg_ds.provider == "DeepSeek"
    assert cfg_ds.model_name == "deepseek-flash"

    # Set API key
    panel.txt_api_key.setText("sk-mysecretkey")
    assert panel.get_config().api_key == "sk-mysecretkey"

    # Test settings persistence
    settings = QSettings(str(tmp_path / "test_settings.ini"), QSettings.IniFormat)
    panel.save_settings(settings)

    panel2 = LLMPanel()
    qtbot.addWidget(panel2)
    panel2.load_settings(settings)
    cfg_loaded = panel2.get_config()
    assert cfg_loaded.enabled is True
    assert cfg_loaded.provider == "DeepSeek"
    assert cfg_loaded.model_name == "deepseek-flash"
    assert cfg_loaded.api_key == "sk-mysecretkey"


def test_main_window_init(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert "Whisper GUI" in window.windowTitle()
    assert not window.windowIcon().isNull()
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    assert window.track_list is not None
    assert window.range_selector is not None
    assert window.settings_panel is not None
    assert window.llm_panel is not None
    assert window.transcript_view is not None
    assert window.config_tabs.count() == 3

    # In-window settings page navigation
    assert window.page_stack.currentIndex() == 0
    window.btn_open_settings.click()
    assert window.page_stack.currentIndex() == 1

    # Wheel scrolling over controls does not change selection
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    combo = window.settings_panel.combo_threads
    init_val = combo.value()
    evt = QWheelEvent(QPoint(10, 10), QPoint(10, 10), QPoint(0, 0), QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
    QApplication.sendEvent(combo, evt)
    assert combo.value() == init_val

    window.settings_page.btn_back.click()
    assert window.page_stack.currentIndex() == 0
    assert "Model:" in window.lbl_model_badge.text()


def test_lateral_tracks_drawer(qtbot):
    from pathlib import Path
    from whisper_gui.models import AudioTrack, AudioInfo

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    # Initial drawer state & dropzone
    assert not window.tracks_drawer.isVisible()
    assert window.dropzone_card.isVisible()
    assert window.lbl_drop_title.text() == "Import File"
    assert window.btn_toggle_drawer.text() == "Tracks (0)"
    assert window.btn_start.text() == "Transcribe Audio"

    # Toggle drawer open
    window.btn_toggle_drawer.click()
    assert window.tracks_drawer.isVisible()
    assert window.btn_toggle_drawer.isChecked()
    assert window.main_splitter.handleWidth() == 12

    # Close drawer via close button
    close_btns = [b for b in window.tracks_drawer.findChildren(object) if hasattr(b, "objectName") and b.objectName() == "btn_close_drawer"]
    assert len(close_btns) == 1
    close_btns[0].click()
    assert not window.tracks_drawer.isVisible()
    assert not window.btn_toggle_drawer.isChecked()

    # Add single track
    p1 = Path("/tmp/meeting1.mp3")
    info1 = AudioInfo(path=p1, duration=120.0, sample_rate=16000, channels=1, size_bytes=2048000, filename="meeting1.mp3", format_name="mp3")
    track1 = AudioTrack(p1, info1)
    window.track_list._tracks.append(track1)
    window.track_list._track_map[track1.id] = track1
    window.track_list._refresh_table()
    window.track_list.track_count_changed.emit(1)

    assert window.btn_toggle_drawer.text() == "Tracks (1)"
    assert window.btn_start.text() == "Transcribe Track"
    assert window.lbl_active_name.text() == "meeting1.mp3"

    # Add second track (multi-track queue)
    p2 = Path("/tmp/interview.mp3")
    info2 = AudioInfo(path=p2, duration=300.0, sample_rate=16000, channels=1, size_bytes=5120000, filename="interview.mp3", format_name="mp3")
    track2 = AudioTrack(p2, info2)
    window.track_list._tracks.append(track2)
    window.track_list._track_map[track2.id] = track2
    window.track_list._refresh_table()
    window.track_list.track_count_changed.emit(2)

    assert window.btn_toggle_drawer.text() == "Tracks (2)"
    assert window.btn_start.text() == "Transcribe All (2 Tracks)"
    assert window.tracks_drawer.isVisible()
    assert window.btn_active_drawer.isVisible()

    # Select track 2 in drawer table
    window.track_list.table.selectRow(1)
    assert window.lbl_active_name.text() == "Track 2 of 2: interview.mp3"

    # Select track 1 in drawer table
    window.track_list.table.selectRow(0)
    assert window.lbl_active_name.text() == "Track 1 of 2: meeting1.mp3"

    # Rename active track via context menu updates active card and compatibility combo
    with patch.object(window.track_list, "_prompt_track_name", return_value=("Opening Remarks.mp3", True)):
        menu = window.track_list.build_context_menu(0)
        assert menu is not None
        menu.actions()[0].trigger()
    assert window.lbl_active_name.text() == "Track 1 of 2: Opening Remarks.mp3"
    assert window.combo_active_track.itemText(0) == "1. Opening Remarks.mp3"

    # Remove track 1 via context menu action updates MainWindow count and active track
    menu.actions()[1].trigger()
    assert window.btn_toggle_drawer.text() == "Tracks (1)"
    assert window.lbl_active_name.text() == "interview.mp3"


def test_settings_panel_delete_cached_model(qtbot, tmp_path, monkeypatch):
    fake_cache = tmp_path / "hf_cache"
    fake_cache.mkdir()
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(fake_cache))

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    idx_tiny = panel.combo_model.findData("tiny")
    panel.combo_model.setCurrentIndex(idx_tiny)
    assert not panel.btn_delete_model.isEnabled()
    assert "Not cached locally" in panel.lbl_disk_status.text()

    snap_dir = fake_cache / "models--Systran--faster-whisper-tiny" / "snapshots" / "main"
    snap_dir.mkdir(parents=True)
    (snap_dir / "model.bin").write_bytes(b"a" * (512 * 1024))

    panel._update_disk_status()
    assert panel.btn_delete_model.isEnabled()
    assert "Downloaded on disk" in panel.lbl_disk_status.text()

    # Cancel confirmation keeps model cache
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.No):
        panel.btn_delete_model.click()
    assert snap_dir.exists()
    assert panel.btn_delete_model.isEnabled()

    # Confirm deletion removes model cache and disables button
    with patch("PySide6.QtWidgets.QMessageBox.question", return_value=QMessageBox.Yes):
        panel.btn_delete_model.click()
    assert not (fake_cache / "models--Systran--faster-whisper-tiny").exists()
    assert not panel.btn_delete_model.isEnabled()
    assert "Not cached locally" in panel.lbl_disk_status.text()


def test_manual_check_for_updates_no_update(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    signal_hits = []
    window.settings_panel.check_updates_requested.connect(lambda: signal_hits.append(True))

    monkeypatch.setattr("whisper_gui.ui.update_dialog.fetch_latest_release", lambda _v: None)

    info_calls = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: info_calls.append(args) or QMessageBox.Ok),
    )

    window.settings_panel.btn_check_updates.click()
    qtbot.waitUntil(lambda: window._update_check_worker is None, timeout=3000)

    assert len(signal_hits) == 1
    assert len(info_calls) == 1
    assert "no updates available" in (info_calls[0][1] + " " + info_calls[0][2]).lower()

    # Background (non-manual) check stays silent when up to date
    info_calls.clear()
    window._check_for_updates(manual=False)
    qtbot.waitUntil(lambda: window._update_check_worker is None, timeout=3000)
    assert len(info_calls) == 0
    window.close()


def test_transcript_view_load_track(qtbot, tmp_path):
    view = TranscriptView()
    qtbot.addWidget(view)
    cfg = TranscriptionConfig()

    # Load None -> Idle and disabled actions
    view.load_track(None, cfg)
    assert view.lbl_status.text() == "Idle"
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_export.isEnabled()
    assert not view.btn_open_folder.isEnabled()
    assert not view.btn_view_polished.isEnabled()

    # Queued track (result is None)
    queued = AudioTrack(
        tmp_path / "queued.mp3",
        AudioInfo(path=tmp_path / "queued.mp3", filename="queued.mp3", duration=30.0),
    )
    queued.status = TrackStatus.QUEUED
    queued.status_message = "Queued"

    # Completed raw-only track with all 4 export paths
    docx_p = tmp_path / "raw.docx"
    pdf_p = tmp_path / "raw.pdf"
    md_p = tmp_path / "raw.md"
    txt_p = tmp_path / "raw.txt"
    for p in (docx_p, pdf_p, md_p, txt_p):
        p.touch()

    raw_track = AudioTrack(
        tmp_path / "raw.mp3",
        AudioInfo(path=tmp_path / "raw.mp3", filename="raw.mp3", duration=60.0),
    )
    raw_track.status = TrackStatus.COMPLETED
    raw_track.progress_percent = 100
    raw_track.status_message = "Completed (4.0x real-time)"
    raw_track.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=3.0, text="Raw segment one")],
        full_text="Raw segment one",
        docx_path=docx_p,
        pdf_path=pdf_p,
        md_path=md_p,
        txt_path=txt_p,
    )

    # Completed polished track
    polished_docx = tmp_path / "polished.docx"
    polished_docx.touch()
    polished_track = AudioTrack(
        tmp_path / "polished.mp3",
        AudioInfo(path=tmp_path / "polished.mp3", filename="polished.mp3", duration=90.0),
    )
    polished_track.status = TrackStatus.COMPLETED
    polished_track.progress_percent = 100
    polished_track.status_message = "Completed (2.5x real-time)"
    polished_track.result = TranscriptionResult(
        segments=[TranscriptSegment(start=1.0, end=4.0, text="Unpolished words")],
        full_text="Unpolished words",
        polished_text="Polished clean paragraph.",
        llm_model_used="deepseek-flash",
        docx_path=polished_docx,
    )

    # Load polished track -> polished mode active, export enabled
    view.load_track(polished_track, cfg)
    assert view._current_track is polished_track
    assert view._current_result is polished_track.result
    assert view._current_config is cfg
    assert view._exported_paths == {"docx": polished_docx}
    assert view.btn_export.isEnabled()
    assert view.btn_open_folder.isEnabled()
    assert view.btn_view_polished.isEnabled()
    assert view.btn_view_polished.isChecked()
    assert view.txt_display.toPlainText() == "Polished clean paragraph."
    assert "Completed (2.5x real-time)" in view.lbl_status.text()
    assert view.lbl_metrics.text() == ""

    # Toggle to raw on polished track
    view.btn_view_raw.click()
    assert "Unpolished words" in view.txt_display.toPlainText()

    # Load raw-only track -> raw mode active, polished disabled, all 4 paths restored
    view.load_track(raw_track, cfg)
    assert view._current_track is raw_track
    assert view._exported_paths == {
        "docx": docx_p,
        "pdf": pdf_p,
        "md": md_p,
        "txt": txt_p,
    }
    assert view.btn_export.isEnabled()
    assert view.btn_open_folder.isEnabled()
    assert not view.btn_view_polished.isEnabled()
    assert view.btn_view_raw.isChecked()
    assert "Raw segment one" in view.txt_display.toPlainText()

    # Load queued track -> cleared and disabled
    view.load_track(queued, cfg)
    assert view._current_track is queued
    assert view._current_result is None
    assert view._exported_paths == {}
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_export.isEnabled()
    assert not view.btn_open_folder.isEnabled()
    assert not view.btn_view_polished.isEnabled()
    assert view.lbl_status.text() == "Queued"

    # Reload polished track -> segments and polished text are still intact
    view.load_track(polished_track, cfg)
    assert view.txt_display.toPlainText() == "Polished clean paragraph."
    view.btn_view_raw.click()
    assert "Unpolished words" in view.txt_display.toPlainText()


def test_main_window_track_switching(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)

    p1 = tmp_path / "one.mp3"
    p2 = tmp_path / "two.mp3"
    p3 = tmp_path / "three.mp3"
    doc1 = tmp_path / "one.docx"
    md2 = tmp_path / "two.md"
    doc1.touch()
    md2.touch()

    t1 = AudioTrack(p1, AudioInfo(path=p1, filename="one.mp3", duration=60.0))
    t1.status = TrackStatus.COMPLETED
    t1.progress_percent = 100
    t1.status_message = "Completed (3.0x real-time)"
    t1.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Track one raw")],
        full_text="Track one raw",
        polished_text="Track one polished",
        llm_model_used="deepseek-flash",
        docx_path=doc1,
    )

    t2 = AudioTrack(p2, AudioInfo(path=p2, filename="two.mp3", duration=45.0))
    t2.status = TrackStatus.COMPLETED
    t2.progress_percent = 100
    t2.status_message = "Completed (5.0x real-time)"
    t2.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.5, text="Track two raw")],
        full_text="Track two raw",
        md_path=md2,
    )

    t3 = AudioTrack(p3, AudioInfo(path=p3, filename="three.mp3", duration=30.0))
    t3.status = TrackStatus.QUEUED
    t3.status_message = "Queued"

    for t in (t1, t2, t3):
        window.track_list._tracks.append(t)
        window.track_list._track_map[t.id] = t
    window.track_list._refresh_table()
    window.track_list.track_count_changed.emit(3)

    assert window._active_track is t1
    assert window.transcript_view.txt_display.toPlainText() == "Track one polished"
    assert window.transcript_view.btn_export.isEnabled()
    assert window.transcript_view.btn_view_polished.isEnabled()

    window.track_list.table.selectRow(1)
    assert window._active_track is t2
    assert "Track two raw" in window.transcript_view.txt_display.toPlainText()
    assert not window.transcript_view.btn_view_polished.isEnabled()
    assert window.transcript_view.btn_export.isEnabled()
    assert window.transcript_view._exported_paths == {"md": md2}

    window.track_list.table.selectRow(2)
    assert window._active_track is t3
    assert window.transcript_view.txt_display.toPlainText() == ""
    assert not window.transcript_view.btn_export.isEnabled()
    assert not window.transcript_view.btn_open_folder.isEnabled()
    assert window.transcript_view.lbl_status.text() == "Queued"

    window.track_list.table.selectRow(0)
    assert window._active_track is t1
    assert window.transcript_view.txt_display.toPlainText() == "Track one polished"
    assert window.transcript_view.btn_export.isEnabled()
    assert window.transcript_view._exported_paths == {"docx": doc1}

    window._on_worker_track_started(t3.id)
    assert window._active_track is t3
    assert window.transcript_view.txt_display.toPlainText() == ""
    assert window.transcript_view.lbl_status.text() == "Transcribing three.mp3..."

    window._on_worker_segment_received(t1.id, TranscriptSegment(start=0.0, end=1.0, text="Wrong track"))
    window._on_worker_progress_updated(t1.id, 99, "99%")
    window._on_worker_track_error(t1.id, "Ignored error")
    assert "Wrong track" not in window.transcript_view.txt_display.toPlainText()
    assert window.transcript_view.progress_bar.value() == 0
    assert window.transcript_view.lbl_status.text() == "Transcribing three.mp3..."

    window._on_worker_segment_received(t3.id, TranscriptSegment(start=0.0, end=1.0, text="Track three live"))
    window._on_worker_progress_updated(t3.id, 50, "15.0s / 30.0s (50%)")
    assert "Track three live" in window.transcript_view.txt_display.toPlainText()
    assert window.transcript_view.progress_bar.value() == 50

    res3 = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=1.0, text="Track three live")],
        full_text="Track three live",
        polished_text="Track three polished",
    )
    window._on_worker_track_completed(t3.id, res3)
    assert t3.result is res3
    assert window.transcript_view.txt_display.toPlainText() == "Track three polished"
    assert window.transcript_view.btn_export.isEnabled()


def test_transcript_view_polish_button(qtbot, tmp_path):
    view = TranscriptView()
    qtbot.addWidget(view)

    assert not view.btn_polish.isEnabled()
    assert view.btn_polish.text() == "Polish"

    audio_path = tmp_path / "clip.wav"
    audio_path.touch()
    info = AudioInfo(path=audio_path, filename="clip.wav", duration=10.0)
    track = AudioTrack(audio_path, info)
    result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="um raw speech")],
        full_text="um raw speech",
    )
    view.set_completed_track(track, result)
    assert view.btn_polish.isEnabled()
    assert view.btn_polish.text() == "Polish"

    with qtbot.waitSignal(view.polish_requested, timeout=1000):
        view.btn_polish.click()

    result.polished_text = "Raw speech."
    view.set_polished_text("Raw speech.", "deepseek-flash")
    assert view.btn_polish.isEnabled()
    assert view.btn_polish.text() == "Re-polish"

    view.clear_view()
    assert not view.btn_polish.isEnabled()
    assert view.btn_polish.text() == "Polish"


def test_main_window_repolish_flow(qtbot, tmp_path):
    import gc
    from PySide6.QtWidgets import QApplication

    def _run():
        window = MainWindow()
        try:
            p1 = tmp_path / "sample.wav"
            p1.touch()
            info1 = AudioInfo(path=p1, duration=10.0, filename="sample.wav")
            track1 = AudioTrack(p1, info1)
            track1.result = TranscriptionResult(
                segments=[TranscriptSegment(start=0.0, end=2.0, text="um hello there")],
                full_text="um hello there",
            )
            window.track_list._tracks.append(track1)
            window.track_list._track_map[track1.id] = track1
            window.track_list._refresh_table()
            window._on_track_selected(track1)

            assert window.transcript_view.btn_polish.isEnabled()
            assert window.transcript_view.btn_polish.text() == "Polish"

            window.llm_panel.combo_provider.setCurrentText("DeepSeek")
            window.llm_panel.txt_api_key.setText("")
            with patch("PySide6.QtWidgets.QMessageBox.warning") as mock_warn:
                window.transcript_view.btn_polish.click()
            mock_warn.assert_called_once()
            assert window.page_stack.currentIndex() == 1

            window.settings_page.btn_back.click()
            window.llm_panel.txt_api_key.setText("sk-valid-key")

            with patch("whisper_gui.worker.polish_transcript", return_value="Hello there."):
                window.transcript_view.btn_polish.click()
                assert window._polish_worker is not None
                qtbot.waitUntil(lambda: window._polish_worker is None, timeout=5000)

            assert window.transcript_view.txt_display.toPlainText() == "Hello there."
            assert window.transcript_view.btn_polish.text() == "Re-polish"
            assert window.transcript_view.btn_polish.isEnabled()
            assert window.btn_start.isEnabled()
            assert "polished" in window.status_bar.currentMessage().lower()
        finally:
            with patch.object(window, "_save_settings"):
                window.close()
            window.deleteLater()
            QApplication.processEvents()

    _run()
    gc.collect()


def test_transcript_view_find_bar(qtbot):
    view = TranscriptView()
    qtbot.addWidget(view)
    view.show()

    assert not view.find_bar.isVisible()

    view.append_segment(TranscriptSegment(start=0.0, end=2.0, text="Alpha beta gamma"))
    view.append_segment(TranscriptSegment(start=2.0, end=4.0, text="Beta delta beta"))

    view.btn_find.click()
    assert view.find_bar.isVisible()

    view.txt_find.setText("beta")
    assert view.lbl_find_status.text() == "1 of 3"
    assert view.txt_display.textCursor().selectedText().lower() == "beta"

    view.btn_find_next.click()
    assert view.lbl_find_status.text() == "2 of 3"

    view.btn_find_next.click()
    assert view.lbl_find_status.text() == "3 of 3"

    view.btn_find_next.click()
    assert view.lbl_find_status.text() == "1 of 3"

    view.btn_find_prev.click()
    assert view.lbl_find_status.text() == "3 of 3"

    view.txt_find.setText("nonexistent")
    assert view.lbl_find_status.text() == "0 matches"

    view.btn_find_close.click()
    assert not view.find_bar.isVisible()

    view.find_shortcut.activated.emit()
    assert view.find_bar.isVisible()


def test_transcript_view_inline_edit_export(qtbot, tmp_path):
    view = TranscriptView()
    qtbot.addWidget(view)

    try:
        assert not view.txt_display.isReadOnly()

        audio_path = tmp_path / "sample.wav"
        audio_path.touch()
        track = AudioTrack(audio_path, AudioInfo(path=audio_path, filename="sample.wav", duration=10.0))
        seg = TranscriptSegment(start=0.0, end=5.0, text="Original raw text")
        result = TranscriptionResult(
            segments=[seg],
            full_text="Original raw text",
            polished_text="Original polished text",
        )

        view.append_segment(seg)
        view.set_polished_text(result.polished_text, "test-model")
        view.set_completed_track(track, result)

        view.txt_display.setPlainText("Edited polished text")
        assert view._polished_text == "Edited polished text"
        assert result.polished_text == "Edited polished text"

        with patch("whisper_gui.ui.transcript_view.open_path_in_os", return_value=False):
            view._on_export_format("txt")
        txt_out = tmp_path / "sample_transcript.txt"
        assert txt_out.exists()
        assert "Edited polished text" in txt_out.read_text(encoding="utf-8")

        view.btn_view_raw.click()
        view.txt_display.setPlainText("Completely edited raw text")
        assert result.full_text == "Completely edited raw text"

        result.polished_text = None
        view._polished_text = None
        with patch("whisper_gui.ui.transcript_view.open_path_in_os", return_value=False):
            view._on_export_format("txt")
            view._on_export_format("srt")

        txt_content = txt_out.read_text(encoding="utf-8")
        assert "Completely edited raw text" in txt_content
        assert "Original raw text" not in txt_content

        srt_out = tmp_path / "sample_transcript.srt"
        assert srt_out.exists()
        assert "Completely edited raw text" in srt_out.read_text(encoding="utf-8")
    finally:
        view.release_player()
        view.close()


def _write_test_wav(path: Path, duration_sec: int = 3, sample_rate: int = 16000) -> None:
    import wave

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * (sample_rate * duration_sec))


def test_trim_audio_dialog_preview_and_close(qtbot, tmp_path):
    wav_path = tmp_path / "preview.wav"
    _write_test_wav(wav_path, duration_sec=3)

    info = AudioInfo(path=wav_path, filename="preview.wav", duration=3.0, sample_rate=16000, channels=1)
    track = AudioTrack(wav_path, info)

    dialog = TrimAudioDialog(track)
    qtbot.addWidget(dialog)

    assert dialog.btn_play_pause.text() == "Play"
    assert dialog.btn_play_selection.text() == "Preview Range"
    assert dialog.lbl_playback_pos.text() == "00:00:00 / 00:00:00"
    assert dialog.btn_play_pause.isEnabled()
    assert dialog.btn_play_selection.isEnabled()
    assert dialog._player is not None

    dialog.btn_play_pause.click()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "Pause", timeout=2000)
    dialog.btn_play_pause.click()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "Play", timeout=2000)

    track.slice_config = SliceConfig(mode=SliceMode.RANGE, start_sec=1.0, end_sec=2.0)
    dialog.selector.set_track(track)
    dialog.btn_play_selection.click()
    assert dialog._preview_end_ms == 2000
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "Pause", timeout=2000)

    dialog._on_position_changed(2000)
    assert dialog._preview_end_ms is None
    assert "00:00:02" in dialog.lbl_playback_pos.text()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "Play", timeout=2000)

    dialog.close()
    assert dialog._player is None
    assert dialog._audio_output is None
    QApplication.processEvents()


def test_trim_audio_dialog_missing_file_and_accept_reject(qtbot, tmp_path):
    missing_path = tmp_path / "missing.wav"
    info = AudioInfo(path=missing_path, filename="missing.wav", duration=5.0)
    track = AudioTrack(missing_path, info)

    dialog = TrimAudioDialog(track)
    qtbot.addWidget(dialog)
    assert dialog._player is None
    assert not dialog.btn_play_pause.isEnabled()
    assert not dialog.btn_play_selection.isEnabled()
    dialog.reject()

    wav_path = tmp_path / "accept_test.wav"
    _write_test_wav(wav_path, duration_sec=2)
    track2 = AudioTrack(wav_path, AudioInfo(path=wav_path, filename="accept_test.wav", duration=2.0))
    dialog2 = TrimAudioDialog(track2)
    qtbot.addWidget(dialog2)
    dialog2.btn_play_pause.click()
    dialog2.accept()
    assert dialog2._player is None
    assert dialog2._audio_output is None
    QApplication.processEvents()


def test_dropzone_hover_and_settings_button_fit(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(960, 760)
    win.show()
    QApplication.processEvents()

    assert not win.dropzone_card._hovered
    assert "COLOR_PRIMARY" not in win.dropzone_card.styleSheet()
    win.dropzone_card.enterEvent(None)
    assert win.dropzone_card._hovered
    win.dropzone_card.leaveEvent(None)
    assert not win.dropzone_card._hovered

    win._open_settings_page()
    QApplication.processEvents()
    btn = win.settings_panel.btn_check_updates
    assert btn.minimumHeight() <= btn.height() <= btn.maximumHeight()
    assert btn.geometry().bottom() <= win.settings_panel.rect().bottom()


def test_theme_switching_drop_animation(qtbot):
    from PySide6.QtCore import QSettings, QSize
    from whisper_gui.ui.theme import get_palette, get_theme_name, load_tinted_pixmap, set_theme

    icon_pm = load_tinted_pixmap("icons/settings.svg", 16, "#52323F")
    assert not icon_pm.isNull()
    assert icon_pm.devicePixelRatio() == 2.0
    assert icon_pm.deviceIndependentSize().toSize() == QSize(16, 16)
    img = icon_pm.toImage()
    # Verify painted pixels extend into the bottom-right quadrant (no HiDPI quarter-crop)
    assert any(img.pixelColor(x, y).alpha() > 0 for x in range(20, 32) for y in range(20, 32))

    qsettings = QSettings("WhisperGUI", "WhisperAudioTranscriber")
    prev_theme = qsettings.value("Settings/theme", "graphite", type=str)
    set_theme("graphite")
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()
        win.resize(960, 680)
        win._open_settings_page()
        win.show()
        QApplication.processEvents()

        assert get_theme_name() == "graphite"
        assert win.settings_panel.btn_theme_graphite.isChecked()

        win.settings_panel.btn_theme_blush.click()
        assert get_theme_name() == "blush"
        palette = get_palette()
        assert palette.bg_surface == "#F8C8DC"
        assert palette.bg_window == "#F3CFC6"
        assert win._theme_overlay is not None

        win.settings_panel.btn_theme_graphite.click()
        assert get_theme_name() == "graphite"
        assert win._theme_overlay is not None
        if win._theme_overlay is not None:
            win._theme_overlay.cancel()
            win._theme_overlay = None
        win.close()
    finally:
        set_theme("graphite")
        qsettings.setValue("Settings/theme", prev_theme)
        QApplication.processEvents()


def test_toggle_switch_drag_and_tap(qtbot):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from whisper_gui.ui.theme import ToggleSwitch

    sw = ToggleSwitch("Test toggle")
    qtbot.addWidget(sw)
    sw.resize(sw.sizeHint())
    sw.show()
    QApplication.processEvents()

    def send_mouse(kind, x: float, buttons=Qt.LeftButton, button=Qt.LeftButton):
        pos = QPointF(x, sw.height() / 2.0)
        ev = QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier)
        QApplication.sendEvent(sw, ev)

    # 1. Plain tap toggles ON
    assert not sw.isChecked()
    send_mouse(QEvent.Type.MouseButtonPress, 10.0)
    send_mouse(QEvent.Type.MouseButtonRelease, 11.0, Qt.NoButton)
    assert sw.isChecked()

    # 2. Partial drag back from ON (< 0.5 distance from 1.0 -> stays >= 0.5) cancels cleanly
    sw._anim.stop()
    sw._pos = 1.0
    send_mouse(QEvent.Type.MouseButtonPress, 26.0)
    send_mouse(QEvent.Type.MouseMove, 20.0)  # -6px -> _pos = 0.625 (midway)
    assert 0.5 < sw._pos < 0.75
    send_mouse(QEvent.Type.MouseButtonRelease, 20.0, Qt.NoButton)
    assert sw.isChecked()
    qtbot.waitUntil(lambda: abs(sw._pos - 1.0) < 0.01, timeout=1000)

    # 3. Full drag back from ON past midpoint flips OFF
    send_mouse(QEvent.Type.MouseButtonPress, 26.0)
    send_mouse(QEvent.Type.MouseMove, 14.0)  # -12px -> _pos = 0.25 (< 0.5)
    assert 0.2 <= sw._pos <= 0.3
    send_mouse(QEvent.Type.MouseButtonRelease, 14.0, Qt.NoButton)
    assert not sw.isChecked()
    qtbot.waitUntil(lambda: abs(sw._pos - 0.0) < 0.01, timeout=1000)

    # 4. Partial drag forward from OFF (< 0.5) cancels and snaps back to 0.0
    send_mouse(QEvent.Type.MouseButtonPress, 10.0)
    send_mouse(QEvent.Type.MouseMove, 15.0)  # +5px -> _pos = 0.3125
    assert 0.25 < sw._pos < 0.5
    send_mouse(QEvent.Type.MouseButtonRelease, 15.0, Qt.NoButton)
    assert not sw.isChecked()
    qtbot.waitUntil(lambda: abs(sw._pos - 0.0) < 0.01, timeout=1000)

    # 5. Full drag forward past midpoint flips ON
    send_mouse(QEvent.Type.MouseButtonPress, 10.0)
    send_mouse(QEvent.Type.MouseMove, 22.0)  # +12px -> _pos = 0.75
    assert sw._pos >= 0.7
    send_mouse(QEvent.Type.MouseButtonRelease, 22.0, Qt.NoButton)
    assert sw.isChecked()
    qtbot.waitUntil(lambda: abs(sw._pos - 1.0) < 0.01, timeout=1000)


def test_inline_edit_persists_across_tabs_track_switch_and_exports(qtbot, tmp_path):
    from docx import Document
    from whisper_gui.models import LLMConfig

    win = MainWindow()
    qtbot.addWidget(win)

    p1 = tmp_path / "one.wav"
    p2 = tmp_path / "two.wav"
    p1.touch()
    p2.touch()

    stale_docx = tmp_path / "one_transcript.docx"
    stale_docx.write_bytes(b"stale")

    t1 = AudioTrack(p1, AudioInfo(path=p1, filename="one.wav", duration=20.0))
    t1.status = TrackStatus.COMPLETED
    t1.progress_percent = 100
    t1.status_message = "Completed (2.0x real-time)"
    t1.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=4.0, text="Original segment one")],
        full_text="Original segment one",
        polished_text="Original polished one",
        llm_model_used="deepseek-flash",
        docx_path=stale_docx,
    )

    t2 = AudioTrack(p2, AudioInfo(path=p2, filename="two.wav", duration=15.0))
    t2.status = TrackStatus.COMPLETED
    t2.progress_percent = 100
    t2.status_message = "Completed (3.0x real-time)"
    t2.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=3.0, text="Track two text")],
        full_text="Track two text",
    )

    win.track_list._tracks.extend([t1, t2])
    win.track_list._track_map[t1.id] = t1
    win.track_list._track_map[t2.id] = t2
    win.track_list._refresh_table()
    win.track_list.track_count_changed.emit(2)

    view = win.transcript_view
    assert win._active_track is t1
    assert view.txt_display.toPlainText() == "Original polished one"

    # 1. Edit polished text, then switch to Raw and make a freeform edit
    view.txt_display.setPlainText("Edited polished one")
    assert t1.result.polished_text == "Edited polished one"
    assert t1.result.docx_path is None  # invalidated stale export path

    view.btn_view_raw.click()
    assert "Original segment one" in view.txt_display.toPlainText()
    view.txt_display.setPlainText("Freeform edited raw text")
    assert t1.result.full_text == "Freeform edited raw text"
    assert t1.result.raw_segments_stale is True

    # 2. Toggle Polished -> Raw preserves both edits
    view.btn_view_polished.click()
    assert view.txt_display.toPlainText() == "Edited polished one"
    view.btn_view_raw.click()
    assert view.txt_display.toPlainText() == "Freeform edited raw text"

    # 3. Switch to track 2 and back to track 1 -> edits and invalidation persist
    win.track_list.table.selectRow(1)
    assert win._active_track is t2
    assert "Track two text" in view.txt_display.toPlainText()

    win.track_list.table.selectRow(0)
    assert win._active_track is t1
    assert view.txt_display.toPlainText() == "Edited polished one"
    assert "docx" not in view._exported_paths

    view.btn_view_raw.click()
    assert view.txt_display.toPlainText() == "Freeform edited raw text"

    # 4. Exporting regenerates docx/txt/srt with edited content (never stale segments)
    win.llm_panel.chk_raw_appendix.setChecked(True)
    with patch("whisper_gui.ui.transcript_view.open_path_in_os", return_value=False):
        view._on_export_format("docx")
        view._on_export_format("txt")
        view._on_export_format("srt")

    doc = Document(str(stale_docx))
    doc_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Edited polished one" in doc_text
    assert "Freeform edited raw text" in doc_text
    assert "Original segment one" not in doc_text

    txt_content = (tmp_path / "one_transcript.txt").read_text(encoding="utf-8")
    assert "Edited polished one" in txt_content
    assert "Freeform edited raw text" in txt_content
    assert "Original segment one" not in txt_content

    srt_content = (tmp_path / "one_transcript.srt").read_text(encoding="utf-8")
    assert "Freeform edited raw text" in srt_content
    assert "Original segment one" not in srt_content


def test_worker_progress_telemetry_updates_status_and_metrics(qtbot, tmp_path):
    win = MainWindow()
    qtbot.addWidget(win)

    p1 = tmp_path / "telemetry.wav"
    p1.touch()
    t1 = AudioTrack(p1, AudioInfo(path=p1, filename="telemetry.wav", duration=60.0))
    win.track_list._tracks.append(t1)
    win.track_list._track_map[t1.id] = t1
    win.track_list._refresh_table()
    win._set_active_track(t1)

    metrics = "00:30 / 01:00 (50%) · 2.5x · ETA 00:12"
    win._on_worker_progress_updated(t1.id, 50, metrics)

    assert t1.progress_percent == 50
    assert win.transcript_view.progress_bar.value() == 50
    assert win.transcript_view.lbl_metrics.text() == metrics
    assert metrics not in win.status_bar.currentMessage()

    win.page_stack.setCurrentIndex(1)
    win._on_worker_progress_updated(t1.id, 50, metrics)
    assert "telemetry.wav" in win.status_bar.currentMessage()
    assert metrics in win.status_bar.currentMessage()


def test_range_selector_theme_and_trim_dialog_italian_no_clipping(qtbot, tmp_path):
    from whisper_gui.i18n import get_language, set_language
    from whisper_gui.ui.theme import get_theme_name, set_theme

    prev_lang = get_language()
    prev_theme = get_theme_name()
    try:
        set_language("it")
        set_theme("blush")

        p1 = tmp_path / "clip.wav"
        p1.touch()
        track = AudioTrack(p1, AudioInfo(path=p1, filename="clip.wav", duration=185.0))

        dlg = TrimAudioDialog(track)
        qtbot.addWidget(dlg)
        dlg.show()
        QApplication.processEvents()

        assert "#FAE6EE" in dlg.selector.top_bar.styleSheet()
        assert dlg.selector.radio_custom.width() >= dlg.selector.radio_custom.sizeHint().width()
        assert dlg.selector.lbl_selected_length.width() >= dlg.selector.lbl_selected_length.sizeHint().width()
    finally:
        set_language(prev_lang)
        set_theme(prev_theme)


def test_trim_dialog_wide_font_metrics_no_clipping(qtbot, tmp_path):
    from PySide6.QtGui import QFont
    from whisper_gui.i18n import get_language, set_language
    from whisper_gui.ui.theme import build_stylesheet, get_theme_name, set_theme

    app = QApplication.instance()
    prev_lang = get_language()
    prev_theme = get_theme_name()
    prev_font = app.font()
    prev_stylesheet = app.styleSheet()
    try:
        p1 = tmp_path / "wide_metrics.wav"
        p1.touch()
        track = AudioTrack(p1, AudioInfo(path=p1, filename="wide_metrics.wav", duration=185.0))

        # Simulate Windows/Linux wide UI + monospace metrics (>= 320px hints) and extreme wide metrics
        scenarios = [
            ("it", "blush", QFont("Courier New", 16), "\nQRadioButton { font-size: 20px; } QLabel { font-size: 16px; }"),
            ("en", "graphite", QFont("DejaVu Sans", 14), "\nQRadioButton { font-size: 20px; } QLabel { font-size: 16px; }"),
            ("it", "graphite", QFont("Courier New", 18), "\nQRadioButton { font-size: 26px; } QLabel { font-size: 18px; }"),
        ]
        for lang, theme_name, stress_font, extra_qss in scenarios:
            set_language(lang)
            set_theme(theme_name)
            app.setFont(stress_font)

            dlg = TrimAudioDialog(track)
            dlg.setStyleSheet(dlg.styleSheet() + extra_qss)
            dlg.selector.lbl_selected_length.setFont(stress_font)
            qtbot.addWidget(dlg)
            dlg.show()
            QApplication.processEvents()

            sel = dlg.selector
            for w in (
                sel.radio_full,
                sel.radio_custom,
                sel.lbl_selected_length,
                sel.lbl_slider_info,
                sel.time_start,
                sel.time_end,
            ):
                assert w.width() >= w.sizeHint().width(), f"{lang}/{theme_name} clipped {w}: {w.width()} < {w.sizeHint().width()}"

            # Verify non-overlapping row structure inside top_bar
            assert sel.radio_custom.x() >= sel.radio_full.x() + sel.radio_full.width()
            assert sel.lbl_selected_length.y() >= sel.time_start.y() + sel.time_start.height()
            dlg.close()
    finally:
        app.setFont(prev_font)
        app.setStyleSheet(prev_stylesheet)
        set_language(prev_lang)
        set_theme(prev_theme)


def test_llm_panel_presets_and_custom_md_persistence(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from whisper_gui.i18n import get_language, set_language
    from whisper_gui.llm_cleaner import PROMPT_PRESET_IDS, load_instructions
    from whisper_gui.ui.llm_panel import LLMPanel

    monkeypatch.setattr("whisper_gui.credentials.sys.platform", "linux")
    monkeypatch.setattr("whisper_gui.credentials.shutil.which", lambda _name: None)

    prev_lang = get_language()
    try:
        set_language("en")
        panel = LLMPanel()
        qtbot.addWidget(panel)

        preset_data = [panel.combo_preset.itemData(i) for i in range(panel.combo_preset.count())]
        assert preset_data == list(PROMPT_PRESET_IDS)
        assert panel.active_prompt_preset() == "default"

        # Switch to Meeting Notes
        idx_meeting = panel.combo_preset.findData("meeting_notes")
        assert idx_meeting >= 0
        panel.combo_preset.setCurrentIndex(idx_meeting)
        assert panel.active_prompt_preset() == "meeting_notes"
        assert panel.lbl_active_prompt.isHidden()
        cfg_meeting = panel.get_config()
        assert cfg_meeting.prompt_preset == "meeting_notes"
        text_m, _ = load_instructions(cfg_meeting)
        assert "Meeting Notes Instructions" in text_m

        # Import custom .md file overrides preset and adds transient custom item
        md_file = tmp_path / "standup.md"
        md_file.write_text("# Standup Notes\nKeep under 5 bullets.", encoding="utf-8")
        with patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(md_file), "")), patch(
            "PySide6.QtWidgets.QMessageBox.information"
        ):
            panel.btn_import_md.click()

        assert panel.active_prompt_preset() is None
        assert panel.combo_preset.currentData() == "custom"
        assert not panel.lbl_active_prompt.isHidden()
        assert "standup.md" in panel.lbl_active_prompt.text()
        text_c, _ = load_instructions(panel.get_config())
        assert "Standup Notes" in text_c

        # Selecting a preset clears the custom override cleanly
        idx_action = panel.combo_preset.findData("action_items")
        panel.combo_preset.setCurrentIndex(idx_action)
        assert panel.active_prompt_preset() == "action_items"
        assert panel.combo_preset.findData("custom") == -1
        assert panel.lbl_active_prompt.isHidden()

        # Save and load round-trip
        settings = QSettings(str(tmp_path / "preset_settings.ini"), QSettings.IniFormat)
        panel.save_settings(settings)

        panel2 = LLMPanel()
        qtbot.addWidget(panel2)
        panel2.load_settings(settings)
        assert panel2.active_prompt_preset() == "action_items"
        assert panel2.get_config().prompt_preset == "action_items"

        # Live Italian retranslation
        set_language("it")
        panel2.retranslate_ui()
        assert panel2.combo_preset.currentText() == "Azioni da fare"
        assert panel2.lbl_active_prompt.isHidden()
    finally:
        set_language(prev_lang)


def test_transcript_view_preset_menu_and_error_recovery(qtbot, tmp_path):
    from whisper_gui.i18n import get_language, set_language

    prev_lang = get_language()
    try:
        set_language("en")
        view = TranscriptView()
        qtbot.addWidget(view)
        view.show()

        assert not view.polish_error_bar.isVisible()
        assert view.polish_preset_actions["default"].isChecked()

        # Selecting a preset via menu action updates selection & emits signal
        selected = []
        view.preset_selected.connect(selected.append)
        view.polish_preset_actions["executive_summary"].trigger()
        assert selected == ["executive_summary"]
        assert view.polish_preset_actions["executive_summary"].isChecked()
        assert "Executive summary" in view.btn_polish_preset.toolTip()

        # Inline error recovery bar displays actionable hint and buttons
        view.show_polish_error("Authentication failed (401): Bad key")
        assert view.polish_error_bar.isVisible()
        assert "API key" in view.lbl_polish_error.text()

        retry_hits = []
        settings_hits = []
        view.polish_requested.connect(lambda: retry_hits.append(True))
        view.llm_settings_requested.connect(lambda: settings_hits.append(True))

        view.btn_polish_retry.click()
        view.btn_polish_settings.click()
        assert retry_hits == [True]
        assert settings_hits == [True]

        # Retranslation updates error bar buttons & preset labels
        set_language("it")
        view.retranslate_ui()
        assert view.btn_polish_retry.text() == "Riprova"
        assert view.btn_polish_settings.text() == "Impostazioni LLM"
        assert view.polish_preset_actions["executive_summary"].text() == "Sintesi esecutiva"

        # Dismiss hides error bar
        view.btn_polish_err_close.click()
        assert not view.polish_error_bar.isVisible()

        # load_track with llm_error shows error bar; clean track hides it
        err_track = AudioTrack(tmp_path / "e.wav", AudioInfo(path=tmp_path / "e.wav", filename="e.wav", duration=5.0))
        err_track.result = TranscriptionResult(full_text="raw", llm_error="HTTP 429 rate limit")
        view.load_track(err_track)
        assert view.polish_error_bar.isVisible()

        view.set_polished_text("Clean output", "deepseek-flash")
        assert not view.polish_error_bar.isVisible()
    finally:
        set_language(prev_lang)


def test_main_window_polish_preset_sync_elapsed_and_error_recovery(qtbot, tmp_path):
    import gc
    from whisper_gui.i18n import get_language, set_language

    prev_lang = get_language()

    def _run():
        set_language("en")
        window = MainWindow()
        window.show()
        QApplication.processEvents()
        try:
            p1 = tmp_path / "meeting.wav"
            p1.touch()
            track = AudioTrack(p1, AudioInfo(path=p1, filename="meeting.wav", duration=12.0))
            track.result = TranscriptionResult(
                segments=[TranscriptSegment(start=0.0, end=3.0, text="um let us review action items")],
                full_text="um let us review action items",
            )
            window.track_list._tracks.append(track)
            window.track_list._track_map[track.id] = track
            window.track_list._refresh_table()
            window._on_track_selected(track)

            # Selecting preset from TranscriptView menu syncs to LLMPanel
            window.transcript_view.polish_preset_actions["action_items"].trigger()
            assert window.llm_panel.get_config().prompt_preset == "action_items"
            assert "Action items" in window.status_bar.currentMessage()

            # Elapsed timer updates status & metrics live during polishing
            window._start_polish_timer(track.id, "deepseek-flash")
            window._polish_start_time -= 4.2
            window._on_polish_elapsed_tick()
            assert "4s" in window.transcript_view.lbl_status.text()
            assert window.transcript_view.lbl_metrics.text() == "4s"
            assert "4s" in window.status_bar.currentMessage()
            window._stop_polish_timer()

            # Failed polish shows inline recovery bar without modal dialog
            window.llm_panel.combo_provider.setCurrentText("DeepSeek")
            window.llm_panel.txt_api_key.setText("sk-bad-key")
            with patch("whisper_gui.worker.polish_transcript", side_effect=RuntimeError("Authentication failed (401)")):
                window.transcript_view.btn_polish.click()
                assert window._polish_worker is not None
                qtbot.waitUntil(lambda: window._polish_worker is None, timeout=5000)

            assert window.transcript_view.polish_error_bar.isVisible()
            assert "API key" in window.transcript_view.lbl_polish_error.text()
            assert not window.btn_stop.isEnabled()

            # Clicking LLM Settings button navigates directly to Settings page
            window.transcript_view.btn_polish_settings.click()
            assert window.page_stack.currentIndex() == 1

            # Retrying from inline error bar succeeds and clears banner
            window.settings_page.btn_back.click()
            with patch("whisper_gui.worker.polish_transcript", return_value="- [ ] Review action items"):
                window.transcript_view.btn_polish_retry.click()
                assert window._polish_worker is not None
                qtbot.waitUntil(lambda: window._polish_worker is None, timeout=5000)

            assert not window.transcript_view.polish_error_bar.isVisible()
            assert window.transcript_view.txt_display.toPlainText() == "- [ ] Review action items"
        finally:
            with patch.object(window, "_save_settings"):
                window.close()
            window.deleteLater()
            QApplication.processEvents()

    try:
        _run()
        gc.collect()
    finally:
        set_language(prev_lang)


def test_main_window_history_page_and_reopen(qtbot, tmp_path, monkeypatch):
    from whisper_gui.i18n import get_language, set_language

    monkeypatch.setenv("WHISPER_GUI_HISTORY_DIR", str(tmp_path / "hist_dir"))
    prev_lang = get_language()
    set_language("en")
    try:
        win = MainWindow()
        qtbot.addWidget(win)
        win.show()

        assert win.btn_open_history.text() == "History"
        assert win.page_stack.count() == 3

        # Simulate track completion -> auto-persisted to local history
        audio_p = tmp_path / "podcast.wav"
        audio_p.write_bytes(b"wav")
        t1 = AudioTrack(audio_p, AudioInfo(path=audio_p, filename="podcast.wav", duration=42.0))
        win.track_list._tracks.append(t1)
        win.track_list._track_map[t1.id] = t1
        win.track_list._refresh_table()
        win._on_track_selected(t1)

        res = TranscriptionResult(
            segments=[TranscriptSegment(start=0.0, end=2.0, text="Welcome to episode one")],
            full_text="Welcome to episode one",
            detected_language="en",
            audio_duration=42.0,
            elapsed_time=7.0,
            polished_text="Welcome to Episode 1.",
            llm_model_used="deepseek-flash",
        )
        win._on_worker_track_completed(t1.id, res)

        entries = win.history_store.list_entries()
        assert len(entries) == 1
        assert entries[0].filename == "podcast.wav"

        # Clear workspace & remove source audio to prove reopening needs no audio file or re-transcribe
        win.track_list.clear_all()
        audio_p.unlink()
        assert len(win.track_list.get_tracks()) == 0

        # Open History page
        win.btn_open_history.click()
        assert win.page_stack.currentIndex() == 2
        assert win.history_page.lbl_count.text() == "1 transcript"
        assert len(win.history_page._row_widgets) == 1

        # Search filter works
        win.history_page.txt_search.setText("nonexistent-xyz")
        assert win.history_page.lbl_count.text() == "0 transcripts"
        assert win.history_page.empty_card.isVisible()

        win.history_page.txt_search.setText("episode")
        assert win.history_page.lbl_count.text() == "1 transcript"
        assert len(win.history_page._row_widgets) == 1

        # Live IT retranslation on History page & Export All button
        it_idx = win.settings_panel.combo_app_language.findData("it")
        win.settings_panel.combo_app_language.setCurrentIndex(it_idx)
        assert win.btn_open_history.text() == "Cronologia"
        assert win.history_page.page_title.text() == "Cronologia"
        assert win.history_page.btn_clear_all.text() == "Svuota cronologia"
        assert win.track_list.btn_export_all.text() == "Esporta tutto"

        en_idx = win.settings_panel.combo_app_language.findData("en")
        win.settings_panel.combo_app_language.setCurrentIndex(en_idx)

        # Reopen entry -> switches back to Transcribe page with transcript loaded
        win.history_page._row_widgets[0].btn_open.click()
        assert win.page_stack.currentIndex() == 0
        assert len(win.track_list.get_tracks()) == 1
        assert win.transcript_view.txt_display.toPlainText() == "Welcome to Episode 1."
        assert win.transcript_view.btn_export.isEnabled()

        # Delete entry from History page
        win.btn_open_history.click()
        win.history_page._row_widgets[0].btn_delete.click()
        assert win.history_store.list_entries() == []
        assert win.history_page.empty_card.isVisible()
        win.close()
    finally:
        set_language(prev_lang)


def test_batch_export_all_completed_tracks(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("WHISPER_GUI_HISTORY_DIR", str(tmp_path / "hist_batch"))
    win = MainWindow()
    qtbot.addWidget(win)

    assert not win.track_list.btn_export_all.isEnabled()
    assert win.track_list.btn_export_all.text() == "Export All"

    p1 = tmp_path / "alpha.wav"
    p2 = tmp_path / "beta.wav"
    p3 = tmp_path / "pending.wav"
    for p in (p1, p2, p3):
        p.touch()

    t1 = AudioTrack(p1, AudioInfo(path=p1, filename="alpha.wav", duration=20.0))
    t1.status = TrackStatus.COMPLETED
    t1.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Alpha transcript")],
        full_text="Alpha transcript",
    )

    t2 = AudioTrack(p2, AudioInfo(path=p2, filename="beta.wav", duration=30.0))
    t2.status = TrackStatus.COMPLETED
    t2.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Beta transcript")],
        full_text="Beta transcript",
    )

    t3 = AudioTrack(p3, AudioInfo(path=p3, filename="pending.wav", duration=10.0))
    t3.status = TrackStatus.QUEUED

    for t in (t1, t2, t3):
        win.track_list._tracks.append(t)
        win.track_list._track_map[t.id] = t
    win.track_list._refresh_table()
    win.track_list.track_count_changed.emit(3)

    assert win.track_list.btn_export_all.isEnabled()
    assert win.track_list.btn_export_all.text() == "Export All (2)"

    export_dir = tmp_path / "batch_out"
    win.track_list.export_all_requested.emit("md", export_dir)

    alpha_md = export_dir / "alpha_transcript.md"
    beta_md = export_dir / "beta_transcript.md"
    pending_md = export_dir / "pending_transcript.md"
    assert alpha_md.is_file()
    assert beta_md.is_file()
    assert not pending_md.exists()
    assert "Alpha transcript" in alpha_md.read_text(encoding="utf-8")
    assert "Beta transcript" in beta_md.read_text(encoding="utf-8")
    assert t1.result.md_path == alpha_md
    assert t2.result.md_path == beta_md
    assert "Exported 2 file(s) as MD" in win.status_bar.currentMessage()
    win.close()


def test_settings_panel_model_download_progress_and_busy_bar(qtbot, tmp_path, monkeypatch):
    fake_cache = tmp_path / "hf_cache"
    fake_cache.mkdir()
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(fake_cache))

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    idx_small = panel.combo_model.findData("small")
    panel.combo_model.setCurrentIndex(idx_small)
    assert panel.btn_download_model.isEnabled()
    assert panel.btn_download_model.text() == "Download Model"

    def fake_download(model_name, on_progress=None, on_status=None, should_stop=None, local_files_only=False):
        if on_status:
            on_status(f"Downloading '{model_name}': 120.0 / 240.0 MB (50%)")
        if on_progress:
            on_progress(50, "120.0 / 240.0 MB (50%)")
        snap = fake_cache / f"models--Systran--faster-whisper-{model_name}" / "snapshots" / "main"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "model.bin").write_bytes(b"x" * 2048)
        if on_progress:
            on_progress(100, "240.0 / 240.0 MB (100%)")
        return str(snap)

    monkeypatch.setattr("whisper_gui.worker.download_model_with_progress", fake_download)
    panel.btn_download_model.click()
    qtbot.waitUntil(lambda: panel._download_worker is None, timeout=3000)

    assert panel.btn_delete_model.isEnabled()
    assert not panel.btn_download_model.isVisible()
    assert "Downloaded on disk" in panel.lbl_disk_status.text()

    # TranscriptView busy indeterminate mode (-1) and recovery to determinate mode (0..100)
    view = TranscriptView()
    qtbot.addWidget(view)
    view.set_progress(-1, "Loading model weights...")
    assert view.progress_bar.maximum() == 0
    assert view.lbl_metrics.text() == "Loading model weights..."
    view.set_progress(42, "42%")
    assert view.progress_bar.minimum() == 0
    assert view.progress_bar.maximum() == 100
    assert view.progress_bar.value() == 42


def test_transcript_view_playback_and_click_to_seek(qtbot, tmp_path):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QTextCursor

    wav_path = tmp_path / "synced.wav"
    _write_test_wav(wav_path, duration_sec=4)

    info = AudioInfo(path=wav_path, filename="synced.wav", duration=4.0, sample_rate=16000, channels=1)
    track = AudioTrack(wav_path, info)
    track.status = TrackStatus.COMPLETED
    track.result = TranscriptionResult(
        segments=[
            TranscriptSegment(start=0.0, end=1.5, text="First segment"),
            TranscriptSegment(start=1.5, end=3.0, text="Second segment"),
            TranscriptSegment(start=3.0, end=4.0, text="Third segment"),
        ],
        full_text="First segment Second segment Third segment",
        polished_text="Polished summary text.",
        llm_model_used="deepseek-flash",
        audio_duration=4.0,
        elapsed_time=0.5,
    )

    view = TranscriptView()
    qtbot.addWidget(view)
    view.resize(640, 420)
    view.show()
    view.load_track(track)
    QApplication.processEvents()

    assert view.playback_bar.isVisible()
    assert view.btn_play_pause.isEnabled()
    assert view.slider_playback.isEnabled()
    assert view.btn_playback_speed.text() == "1.0x"

    # Cycle playback speeds cleanly
    view.btn_playback_speed.click()
    assert view.btn_playback_speed.text() == "1.25x"
    view.btn_playback_speed.click()
    assert view.btn_playback_speed.text() == "1.5x"
    view.btn_playback_speed.click()
    assert view.btn_playback_speed.text() == "2.0x"
    view.btn_playback_speed.click()
    assert view.btn_playback_speed.text() == "0.75x"
    view.btn_playback_speed.click()
    assert view.btn_playback_speed.text() == "1.0x"

    # Switch to raw view and verify plain-span timestamps (no <a> HTML anchors)
    view.btn_view_raw.click()
    QApplication.processEvents()
    assert "<a " not in view.txt_display.toHtml().lower()
    block1 = view.txt_display.document().findBlockByNumber(1)
    assert block1.isValid()
    click_pos = QPointF(view.txt_display.cursorRect(QTextCursor(block1)).center())

    activated_segments: list[int] = []
    view.segment_activated.connect(activated_segments.append)

    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonPress, click_pos, click_pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonRelease, click_pos, click_pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    QApplication.processEvents()

    assert activated_segments[-1] == 1
    assert view._active_segment_idx == 1
    assert len(view.txt_display.extraSelections()) == 1
    assert "00:02" in view.lbl_playback_time.text() or "00:01" in view.lbl_playback_time.text()

    # Plain click on text body does not seek; Ctrl+click on text body seeks
    block0 = view.txt_display.document().findBlockByNumber(0)
    end_cur = QTextCursor(block0)
    end_cur.movePosition(QTextCursor.EndOfBlock)
    body_pos = QPointF(view.txt_display.cursorRect(end_cur).center())
    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonPress, body_pos, body_pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonRelease, body_pos, body_pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    QApplication.processEvents()
    assert view._active_segment_idx == 1

    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonPress, body_pos, body_pos, Qt.LeftButton, Qt.LeftButton, Qt.ControlModifier),
    )
    QApplication.sendEvent(
        view.txt_display.viewport(),
        QMouseEvent(QEvent.Type.MouseButtonRelease, body_pos, body_pos, Qt.LeftButton, Qt.NoButton, Qt.ControlModifier),
    )
    QApplication.processEvents()
    assert view._active_segment_idx == 0

    # Position updates sync active segment highlight
    view.pause_playback()
    view._on_player_position_changed(3500)
    assert view._active_segment_idx == 2
    assert len(view.txt_display.extraSelections()) == 1

    # Polished mode clears segment highlight; switching back to Raw restores it
    view.btn_view_polished.click()
    assert view.txt_display.extraSelections() == []
    view.btn_view_raw.click()
    assert len(view.txt_display.extraSelections()) == 1

    view.clear_view()
    assert not view.playback_bar.isVisible()
    assert view._player is None
    assert view.txt_display.extraSelections() == []


def test_transcript_view_slice_offset_and_headless_audio_fallback(qtbot, tmp_path):
    wav_path = tmp_path / "trimmed.wav"
    _write_test_wav(wav_path, duration_sec=6)

    info = AudioInfo(path=wav_path, filename="trimmed.wav", duration=6.0, sample_rate=16000, channels=1)
    track = AudioTrack(wav_path, info)
    track.slice_config = SliceConfig(mode=SliceMode.RANGE, start_sec=2.0, end_sec=5.0)
    track.status = TrackStatus.COMPLETED
    track.result = TranscriptionResult(
        segments=[
            TranscriptSegment(start=0.0, end=1.5, text="Slice part one"),
            TranscriptSegment(start=1.5, end=3.0, text="Slice part two"),
        ],
        full_text="Slice part one Slice part two",
        audio_duration=3.0,
        elapsed_time=0.4,
    )

    view = TranscriptView()
    qtbot.addWidget(view)
    view.show()
    view.load_track(track)

    assert view._slice_start_ms == 2000
    assert view._slice_end_ms == 5000

    # Seeking segment 1 (1.5s into slice) targets 3500ms in underlying file
    view.seek_to_segment(1, autoplay=False)
    assert view._active_segment_idx == 1
    assert "00:02" in view.lbl_playback_time.text() or "00:01" in view.lbl_playback_time.text()

    # Headless / missing audio hardware error during player init stays graceful
    with patch("whisper_gui.ui.transcript_view.QMediaPlayer", side_effect=RuntimeError("No audio backend")):
        view._load_track_audio(track)
        assert view._player is None
        assert view.playback_bar.isVisible()
        assert not view.btn_play_pause.isEnabled()
        assert not view.slider_playback.isEnabled()
        # Segment seek still highlights text cleanly even without audio backend
        view.seek_to_segment(0, autoplay=True)
        assert view._active_segment_idx == 0

    view.clear_view()


def test_waveform_scrubber_and_trim_dialog(qtbot, tmp_path):
    import math
    import struct
    import wave
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    wav_path = tmp_path / "wave.wav"
    sr = 16000
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * i / sr)))
        for i in range(sr * 4)
    )
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(frames)

    info = AudioInfo(path=wav_path, filename="wave.wav", duration=4.0, sample_rate=sr, channels=1)
    track = AudioTrack(wav_path, info)

    dialog = TrimAudioDialog(track)
    qtbot.addWidget(dialog)
    dialog.show()
    QApplication.processEvents()

    wf_widget = dialog.selector.waveform
    qtbot.waitUntil(lambda: len(wf_widget._peaks) > 0, timeout=3000)
    assert all(0.0 <= v <= 1.0 for v in wf_widget._peaks)

    # Drag end handle inward to ~50% (2.0s)
    inner = wf_widget._inner_rect()
    end_x = wf_widget._sec_to_x(4.0, inner)
    mid_x = wf_widget._sec_to_x(2.0, inner)
    cy = inner.center().y()

    QApplication.sendEvent(
        wf_widget,
        QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(end_x, cy), QPointF(end_x, cy), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    QApplication.sendEvent(
        wf_widget,
        QMouseEvent(QEvent.Type.MouseMove, QPointF(mid_x, cy), QPointF(mid_x, cy), Qt.NoButton, Qt.LeftButton, Qt.NoModifier),
    )
    QApplication.sendEvent(
        wf_widget,
        QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(mid_x, cy), QPointF(mid_x, cy), Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    assert dialog.selector.radio_custom.isChecked()
    assert 1.5 <= track.slice_config.effective_end(4.0) <= 2.5

    # Click at ~1.0s seeks playhead
    q1_x = wf_widget._sec_to_x(1.0, inner)
    QApplication.sendEvent(
        wf_widget,
        QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(q1_x, cy), QPointF(q1_x, cy), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier),
    )
    QApplication.sendEvent(
        wf_widget,
        QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(q1_x, cy), QPointF(q1_x, cy), Qt.LeftButton, Qt.NoButton, Qt.NoModifier),
    )
    assert 0.7 <= wf_widget._playhead_sec <= 1.3
    assert "00:00:01" in dialog.lbl_playback_pos.text()

    # Verify clean QPainter render
    pm = wf_widget.grab()
    assert not pm.isNull() and pm.width() > 0 and pm.height() > 0

    dialog.close()


def test_combobox_popups_single_frame_and_consistent_height(qtbot):
    import gc
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox, QFrame, QListView, QStyle, QStyleOptionComboBox
    from whisper_gui.i18n import get_language, set_language
    from whisper_gui.ui.theme import BLUSH_PALETTE, GRAPHITE_PALETTE, build_stylesheet, get_theme_name, set_theme

    orig_lang = get_language()
    orig_theme = get_theme_name()

    for pal in (GRAPHITE_PALETTE, BLUSH_PALETTE):
        qss = build_stylesheet(pal)
        assert "combobox-popup: 0;" in qss
        assert "QComboBoxPrivateContainer" in qss
        assert "#qt_scrollarea_vcontainer" in qss

    def _run():
        win = MainWindow()
        win.resize(1100, 820)
        win.show()
        win._open_settings_page()
        QApplication.processEvents()

        try:
            combos = [
                win.settings_panel.combo_app_language,
                win.settings_panel.combo_model,
                win.settings_panel.combo_lang,
                win.settings_panel.combo_device,
                win.settings_panel.combo_compute,
                win.settings_panel.spin_threads,
                win.settings_panel.combo_export_format,
                win.llm_panel.combo_provider,
                win.llm_panel.combo_model,
                win.llm_panel.combo_preset,
                win.combo_active_track,
            ]

            for combo in combos:
                assert isinstance(combo, QComboBox)
                assert combo.maxVisibleItems() == 10
                assert isinstance(combo.view(), QListView)
                assert combo.view().frameShape() == QFrame.Shape.NoFrame
                combo.ensurePolished()
                opt = QStyleOptionComboBox()
                combo.initStyleOption(opt)
                assert combo.style().styleHint(QStyle.StyleHint.SH_ComboBox_Popup, opt, combo) == 0

                container = combo.view().parentWidget()
                assert container is not None
                assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                if sys.platform == "darwin":
                    assert bool(container.windowFlags() & Qt.WindowType.NoDropShadowWindowHint)
                assert container.contentsMargins().isNull()

            # Verify invariant popup size, exact combo width, zero container gap, and scrollbar behavior
            for theme_name in ("graphite", "blush"):
                set_theme(theme_name)
                win.apply_theme()
                QApplication.processEvents()

                for combo in (
                    win.settings_panel.combo_app_language,
                    win.settings_panel.combo_model,
                    win.settings_panel.combo_lang,
                    win.llm_panel.combo_model,
                ):
                    orig_idx = combo.currentIndex()
                    indices = (
                        [0, combo.count() // 2, combo.count() - 1]
                        if combo.count() >= 3
                        else list(range(combo.count()))
                    )
                    geometries = []
                    combo.blockSignals(True)
                    try:
                        for idx in indices:
                            combo.setCurrentIndex(idx)
                            combo.showPopup()
                            QApplication.processEvents()

                            view = combo.view()
                            container = view.parentWidget()
                            assert container.isVisible()
                            assert container.width() == combo.width()
                            assert view.geometry() == container.rect()
                            assert not any(
                                ch.isVisible()
                                for ch in container.children()
                                if "Scroller" in ch.metaObject().className() and hasattr(ch, "isVisible")
                            )
                            assert view.verticalScrollBar().isVisible() == (combo.count() > combo.maxVisibleItems())
                            geometries.append((container.x(), container.y(), container.width(), container.height()))
                            combo.hidePopup()
                            QApplication.processEvents()
                    finally:
                        combo.setCurrentIndex(orig_idx)
                        combo.blockSignals(False)

                    assert len(set(geometries)) == 1, f"{combo} popup geometry varied by selected index: {geometries}"

            for menu in (
                win.transcript_view.export_menu,
                win.transcript_view.polish_preset_menu,
                win.track_list.export_all_menu,
            ):
                assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                if sys.platform == "darwin":
                    assert bool(menu.windowFlags() & Qt.WindowType.NoDropShadowWindowHint)
        finally:
            set_language(orig_lang)
            set_theme(orig_theme)
            with patch.object(win, "_save_settings"):
                win.close()
            win.deleteLater()
            QApplication.processEvents()

    _run()
    gc.collect()


def test_mainwindow_preserves_llm_export_preferences_across_completion_and_pdf_export(qtbot, tmp_path):
    """Disabling chk_raw_appendix and chk_timestamps must hold when exporting PDF/MD/TXT/DOCX."""
    from unittest.mock import patch

    from whisper_gui.exporters import _build_pdf_html

    win = MainWindow()
    qtbot.addWidget(win)
    win.settings_panel.chk_timestamps.setChecked(False)
    win.llm_panel.chk_enable.setChecked(True)
    win.llm_panel.chk_raw_appendix.setChecked(False)

    audio_path = tmp_path / "lecture.wav"
    audio_path.touch()
    track = AudioTrack(
        audio_path,
        AudioInfo(path=audio_path, filename="lecture.wav", duration=60.0),
    )
    win.track_list._tracks.append(track)
    win.track_list._track_map[track.id] = track
    win.track_list._refresh_table()
    win._set_active_track(track)

    assert win.transcript_view._current_config is not None
    assert win.transcript_view._current_config.include_timestamps_in_docx is False
    assert win.transcript_view._current_config.llm_config.include_raw_in_docx is False

    result = TranscriptionResult(
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Raw segment one"),
            TranscriptSegment(start=2.0, end=4.0, text="Raw segment two"),
        ],
        full_text="Raw segment one Raw segment two",
        polished_text="Polished summary paragraph.",
        llm_model_used="deepseek-flash",
    )
    win._on_worker_track_completed(track.id, result)

    cfg_after = win.transcript_view._current_config
    assert cfg_after is not None
    assert cfg_after.include_timestamps_in_docx is False
    assert cfg_after.llm_config.include_raw_in_docx is False

    pdf_html = _build_pdf_html(track.info, track.slice_config, cfg_after, result)
    assert "Polished summary paragraph." in pdf_html
    assert "Detailed Transcript" not in pdf_html
    assert "Raw segment one" not in pdf_html

    with patch("whisper_gui.ui.transcript_view.open_path_in_os", return_value=False):
        win.transcript_view._on_export_format("pdf")
        win.transcript_view._on_export_format("txt")

    txt_content = (tmp_path / "lecture_transcript.txt").read_text(encoding="utf-8")
    assert "Polished summary paragraph." in txt_content
    assert "DETAILED TRANSCRIPT" not in txt_content
    assert "Raw segment one" not in txt_content

    # Re-enabling chk_raw_appendix live invalidates stale cache and regenerates with detailed section
    win.llm_panel.chk_raw_appendix.setChecked(True)
    assert "pdf" not in win.transcript_view._exported_paths
    assert "txt" not in win.transcript_view._exported_paths
    assert result.pdf_path is None
    assert win.transcript_view._current_config.llm_config.include_raw_in_docx is True

    with patch("whisper_gui.ui.transcript_view.open_path_in_os", return_value=False):
        win.transcript_view._on_export_format("txt")
    txt_with_raw = (tmp_path / "lecture_transcript.txt").read_text(encoding="utf-8")
    assert "Raw segment one" in txt_with_raw
    with patch.object(win, "_save_settings"):
        win.close()
