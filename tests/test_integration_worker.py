"""End-to-end integration test: Audio Slicing -> Whisper -> Word .docx export."""

import subprocess
import time
from pathlib import Path
from unittest.mock import patch
import pytest
from docx import Document

from whisper_gui.audio_utils import get_audio_info, get_ffmpeg_cmd
from whisper_gui.models import (
    AudioInfo,
    AudioTrack,
    LLMConfig,
    SliceConfig,
    SliceMode,
    TranscriptSegment,
    TranscriptionConfig,
    TranscriptionResult,
)
from whisper_gui.transcriber import Transcriber
from whisper_gui.worker import PolishWorker, TranscriptionWorker


@pytest.fixture
def test_audio_file(tmp_path: Path) -> Path:
    """Create a 3-second test WAV file with sine wave."""
    wav_file = tmp_path / "test_audio.wav"
    cmd = [
        get_ffmpeg_cmd(), "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=3",
        str(wav_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return wav_file


def test_worker_end_to_end(qtbot, test_audio_file: Path, tmp_path: Path):
    info = get_audio_info(test_audio_file)
    track = AudioTrack(test_audio_file, info)

    # Slice 1 second (from 0.5s to 1.5s)
    track.slice_config = SliceConfig(
        mode=SliceMode.RANGE,
        start_sec=0.5,
        end_sec=1.5,
    )

    out_docx = tmp_path / "output_test.docx"
    track.output_docx_path = out_docx

    # Configure transcription with 'tiny' for fast test execution
    cfg = TranscriptionConfig(
        model_name="tiny",
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        vad_filter=False,  # Sine tone has no voice, vad would drop everything
    )

    transcriber = Transcriber()
    worker = TranscriptionWorker(
        tracks=[track],
        transcription_config=cfg,
        transcriber=transcriber,
    )

    completed_tracks = []
    def on_completed(track_id, result):
        completed_tracks.append((track_id, result))

    worker.track_completed.connect(on_completed)

    with qtbot.waitSignal(worker.batch_finished, timeout=60000):
        worker.start()
    worker.wait(5000)

    assert len(completed_tracks) == 1
    track_id, result = completed_tracks[0]
    assert track_id == track.id
    assert out_docx.exists()

    # Verify Word document
    doc = Document(str(out_docx))
    assert len(doc.tables) >= 1
    doc_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Audio Transcription" in doc_text
    assert "test_audio.wav" in "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)


def test_worker_with_llm_polish(qtbot, test_audio_file: Path, tmp_path: Path):
    import json
    from unittest.mock import MagicMock, patch
    from whisper_gui.models import LLMConfig

    info = get_audio_info(test_audio_file)
    track = AudioTrack(test_audio_file, info)
    out_docx = tmp_path / "output_polished.docx"
    track.output_docx_path = out_docx

    llm_cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4.1-flash",
        api_key="sk-test",
    )
    cfg = TranscriptionConfig(
        model_name="tiny",
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        vad_filter=False,
        llm_config=llm_cfg,
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "Polished audio transcript from DeepSeek."}}]
    }).encode("utf-8")

    from whisper_gui.models import TranscriptSegment, TranscriptionResult
    mock_whisper_result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Raw speech from audio")],
        full_text="Raw speech from audio",
        audio_duration=2.0,
        elapsed_time=1.0,
    )

    transcriber = Transcriber()
    worker = TranscriptionWorker(
        tracks=[track],
        transcription_config=cfg,
        transcriber=transcriber,
    )

    completed_tracks = []
    worker.track_completed.connect(lambda t_id, res: completed_tracks.append((t_id, res)))

    with patch.object(transcriber, "transcribe", return_value=mock_whisper_result), patch("urllib.request.urlopen") as mock_url:
        mock_url.return_value.__enter__.return_value = mock_resp
        with qtbot.waitSignal(worker.batch_finished, timeout=30000):
            worker.start()
        worker.wait(5000)

    assert len(completed_tracks) == 1
    _, result = completed_tracks[0]
    assert result.polished_text == "Polished audio transcript from DeepSeek."
    assert result.llm_model_used == "deepseek-v4.1-flash"
    assert out_docx.exists()

    doc = Document(str(out_docx))
    doc_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Polished & Refined Document" in doc_text
    assert "Polished audio transcript from DeepSeek." in doc_text


def test_worker_auto_export_disabled(qtbot, tmp_path):
    sample_file = tmp_path / "sine_no_export.wav"
    cmd = [get_ffmpeg_cmd(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(sample_file)]
    subprocess.run(cmd, check=True, capture_output=True)

    info = get_audio_info(sample_file)
    track = AudioTrack(sample_file, info)
    out_docx = tmp_path / "should_not_exist.docx"
    track.output_docx_path = out_docx

    cfg = TranscriptionConfig(
        model_name="tiny",
        device="cpu",
        compute_type="int8",
        cpu_threads=1,
        vad_filter=False,
        auto_export=False,
    )

    transcriber = Transcriber()
    mock_result = TranscriptionResult(full_text="Test manual only")

    worker = TranscriptionWorker(tracks=[track], transcription_config=cfg, transcriber=transcriber)
    completed_tracks = []
    worker.track_completed.connect(lambda t_id, res: completed_tracks.append((t_id, res)))

    with patch.object(transcriber, "transcribe", return_value=mock_result):
        with qtbot.waitSignal(worker.batch_finished, timeout=10000):
            worker.start()
        worker.wait(5000)

    assert len(completed_tracks) == 1
    assert not out_docx.exists()


def test_polish_worker_success(qtbot, tmp_path):
    audio_path = tmp_path / "dummy.wav"
    audio_path.touch()
    info = AudioInfo(path=audio_path, filename="dummy.wav", duration=5.0)
    track = AudioTrack(audio_path, info)
    track.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="um hello world")],
        full_text="um hello world",
        llm_error="previous error",
    )

    llm_cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4-pro",
        api_key="sk-test",
    )
    worker = PolishWorker(track=track, llm_config=llm_cfg)

    completed = []
    worker.completed.connect(lambda tid, res: completed.append((tid, res)))

    with patch("whisper_gui.worker.polish_transcript", return_value="Hello world.") as mock_polish:
        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()
        worker.wait(2000)

    mock_polish.assert_called_once()
    assert mock_polish.call_args.kwargs["raw_text"] == "um hello world"
    assert len(completed) == 1
    tid, res = completed[0]
    assert tid == track.id
    assert res.polished_text == "Hello world."
    assert res.llm_model_used == "deepseek-v4-pro"
    assert res.llm_instructions_name == "Default Instructions"
    assert res.llm_error is None


def test_polish_worker_segments_fallback_and_failure(qtbot, tmp_path):
    audio_path = tmp_path / "dummy2.wav"
    audio_path.touch()
    info = AudioInfo(path=audio_path, filename="dummy2.wav", duration=5.0)
    track = AudioTrack(audio_path, info)
    track.result = TranscriptionResult(
        segments=[TranscriptSegment(start=0.0, end=1.0, text="from segments")],
        full_text="",
    )

    llm_cfg = LLMConfig(provider="DeepSeek", model_name="deepseek-flash", api_key="sk-test")
    worker = PolishWorker(track=track, llm_config=llm_cfg)

    failed = []
    worker.failed.connect(lambda tid, msg: failed.append((tid, msg)))

    with patch("whisper_gui.worker.polish_transcript", side_effect=RuntimeError("API down")) as mock_polish:
        with qtbot.waitSignal(worker.finished, timeout=5000):
            worker.start()
        worker.wait(2000)

    assert mock_polish.call_args.kwargs["raw_text"] == "from segments"
    assert failed == [(track.id, "API down")]
    assert track.result.llm_error == "API down"


def test_polish_worker_cancelled(qtbot, tmp_path):
    audio_path = tmp_path / "dummy3.wav"
    audio_path.touch()
    info = AudioInfo(path=audio_path, filename="dummy3.wav", duration=5.0)
    track = AudioTrack(audio_path, info)
    track.result = TranscriptionResult(full_text="some text")

    llm_cfg = LLMConfig(provider="DeepSeek", model_name="deepseek-flash", api_key="sk-test")
    worker = PolishWorker(track=track, llm_config=llm_cfg)
    cancelled_called = []
    worker.cancelled.connect(lambda: cancelled_called.append(True))
    worker.request_stop()
    assert worker.should_stop() is True

    with qtbot.waitSignal(worker.finished, timeout=5000):
        worker.start()
    worker.wait(2000)
    assert cancelled_called == [True]
