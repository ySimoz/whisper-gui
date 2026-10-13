"""GUI widget and window tests using pytest-qt."""

import os
import subprocess
from pathlib import Path
import pytest
from PySide6.QtCore import Qt

# Ensure headless offscreen platform for test runner
os.environ["QT_QPA_PLATFORM"] = "offscreen"

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

    # Switch to custom range
    widget.radio_custom.setChecked(True)
    assert widget.radio_custom.isChecked()

    # Apply 5m preset (300 seconds)
    widget.btn_preset_5m.click()
    assert dummy_track.slice_config.mode == SliceMode.RANGE
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


def test_transcript_view(qtbot, tmp_path):
    view = TranscriptView()
    qtbot.addWidget(view)

    # Initially empty and buttons disabled
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_open_docx.isEnabled()

    # Append segment
    seg = TranscriptSegment(start=2.0, end=5.5, text="Hello Whisper")
    view.append_segment(seg)
    assert "Hello Whisper" in view.txt_display.toPlainText()

    # Update progress
    view.set_progress(50, "50% done")
    assert view.progress_bar.value() == 50

    # Mark completed docx
    fake_docx = tmp_path / "result.docx"
    fake_docx.touch()
    view.set_completed_docx(fake_docx)
    assert view.btn_open_docx.isEnabled()
    assert view.btn_open_folder.isEnabled()

    # Clear view
    view.clear_view()
    assert view.txt_display.toPlainText() == ""
    assert not view.btn_open_docx.isEnabled()


def test_track_list_widget(qtbot, tmp_path):
    # Create sample wav file
    sample_file = tmp_path / "test_track.wav"
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(sample_file)]
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

    # Clear
    widget.clear_all()
    assert len(widget.get_tracks()) == 0
    assert widget.table.rowCount() == 0


def test_main_window_init(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert "Whisper GUI" in window.windowTitle()
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    assert window.track_list is not None
    assert window.range_selector is not None
    assert window.settings_panel is not None
    assert window.transcript_view is not None
