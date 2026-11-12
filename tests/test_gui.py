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
    assert view.lbl_status.text() == "Status: Idle"
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
    assert view.lbl_metrics.text() == "Completed (2.5x real-time)"

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
    assert view.lbl_status.text() == "Status: Queued"

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
    assert window.transcript_view.lbl_status.text() == "Status: Queued"

    window.track_list.table.selectRow(0)
    assert window._active_track is t1
    assert window.transcript_view.txt_display.toPlainText() == "Track one polished"
    assert window.transcript_view.btn_export.isEnabled()
    assert window.transcript_view._exported_paths == {"docx": doc1}

    window._on_worker_track_started(t3.id)
    assert window._active_track is t3
    assert window.transcript_view.txt_display.toPlainText() == ""
    assert window.transcript_view.lbl_status.text() == "Status: Transcribing three.mp3..."

    window._on_worker_segment_received(t1.id, TranscriptSegment(start=0.0, end=1.0, text="Wrong track"))
    window._on_worker_progress_updated(t1.id, 99, "99%")
    window._on_worker_track_error(t1.id, "Ignored error")
    assert "Wrong track" not in window.transcript_view.txt_display.toPlainText()
    assert window.transcript_view.progress_bar.value() == 0
    assert window.transcript_view.lbl_status.text() == "Status: Transcribing three.mp3..."

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
                worker = window._polish_worker
                assert worker is not None
                with qtbot.waitSignal(worker.finished, timeout=5000):
                    pass
                worker.wait(2000)

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

    assert dialog.btn_play_pause.text() == "▶ Play"
    assert dialog.btn_play_selection.text() == "▶ Preview Range"
    assert dialog.lbl_playback_pos.text() == "00:00:00 / 00:00:00"
    assert dialog.btn_play_pause.isEnabled()
    assert dialog.btn_play_selection.isEnabled()
    assert dialog._player is not None

    dialog.btn_play_pause.click()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "⏸ Pause", timeout=2000)
    dialog.btn_play_pause.click()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "▶ Play", timeout=2000)

    track.slice_config = SliceConfig(mode=SliceMode.RANGE, start_sec=1.0, end_sec=2.0)
    dialog.selector.set_track(track)
    dialog.btn_play_selection.click()
    assert dialog._preview_end_ms == 2000
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "⏸ Pause", timeout=2000)

    dialog._on_position_changed(2000)
    assert dialog._preview_end_ms is None
    assert "00:00:02" in dialog.lbl_playback_pos.text()
    qtbot.waitUntil(lambda: dialog.btn_play_pause.text() == "▶ Play", timeout=2000)

    dialog.close()
    assert dialog._player is None
    assert dialog._audio_output is None


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
