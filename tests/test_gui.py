"""GUI widget and window tests using pytest-qt."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

# Ensure headless offscreen platform for test runner
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from whisper_gui.audio_utils import get_ffmpeg_cmd
from whisper_gui.models import AudioInfo, AudioTrack, SliceMode, TranscriptSegment
from whisper_gui.ui.main_window import MainWindow
from whisper_gui.ui.range_selector import RangeSelectorWidget
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
    assert len(view.export_menu.actions()) >= 4

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
    # Create sample wav file
    sample_file = tmp_path / "test_track.wav"
    cmd = [get_ffmpeg_cmd(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(sample_file)]
    subprocess.run(cmd, check=True, capture_output=True)

    widget = TrackListWidget()
    qtbot.addWidget(widget)

    assert len(widget.get_tracks()) == 0

    # Add file
    widget.add_audio_files([sample_file])
    tracks = widget.get_tracks()
    assert len(tracks) == 1
    assert tracks[0].info.filename == "test_track.wav"
    assert widget.table.rowCount() == 1
    assert widget.get_track(tracks[0].id) == tracks[0]
    assert widget.get_track("nonexistent_id") is None

    # Clear
    widget.clear_all()
    assert len(widget.get_tracks()) == 0
    assert widget.table.rowCount() == 0


def test_llm_panel(qtbot, tmp_path):
    from whisper_gui.ui.llm_panel import LLMPanel
    from whisper_gui.models import LLMConfig
    from PySide6.QtCore import QSettings

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
    assert window.btn_toggle_drawer.text() == "☰ Tracks (0)"
    assert window.btn_start.text() == "Transcribe Audio"

    # Toggle drawer open
    window.btn_toggle_drawer.click()
    assert window.tracks_drawer.isVisible()
    assert window.btn_toggle_drawer.isChecked()

    # Close drawer via close button
    close_btns = [b for b in window.tracks_drawer.findChildren(object) if hasattr(b, "text") and b.text() == "✕"]
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

    assert window.btn_toggle_drawer.text() == "☰ Tracks (1)"
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

    assert window.btn_toggle_drawer.text() == "☰ Tracks (2)"
    assert window.btn_start.text() == "Transcribe All (2 Tracks)"
    assert window.tracks_drawer.isVisible()
    assert window.btn_active_drawer.isVisible()

    # Select track 2 in drawer table
    window.track_list.table.selectRow(1)
    assert window.lbl_active_name.text() == "Track 2 of 2: interview.mp3"

    # Select track 1 in drawer table
    window.track_list.table.selectRow(0)
    assert window.lbl_active_name.text() == "Track 1 of 2: meeting1.mp3"
