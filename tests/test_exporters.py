"""Unit tests for multi-format exporters (PDF, Markdown, Plain Text, DOCX)."""

from pathlib import Path

from whisper_gui.exporters import (
    export_transcript,
    export_transcript_to_docx,
    export_transcript_to_md,
    export_transcript_to_pdf,
    export_transcript_to_txt,
)
from whisper_gui.models import (
    AudioInfo,
    SliceConfig,
    SliceMode,
    TranscriptSegment,
    TranscriptionConfig,
    TranscriptionResult,
)


def _make_sample_data():
    track_info = AudioInfo(
        path=Path("/media/interview.mp3"),
        filename="interview.mp3",
        duration=300.0,
        format_name="mp3",
        sample_rate=44100,
        channels=2,
    )
    slice_cfg = SliceConfig(mode=SliceMode.RANGE, start_sec=10.0, end_sec=70.0)
    tx_cfg = TranscriptionConfig(
        model_name="large-v3-turbo",
        language="en",
        include_timestamps_in_docx=True,
    )
    segments = [
        TranscriptSegment(start=10.0, end=15.0, text="Welcome to the interview."),
        TranscriptSegment(start=15.5, end=22.0, text="Thank you for having me today."),
    ]
    result = TranscriptionResult(
        segments=segments,
        full_text="Welcome to the interview. Thank you for having me today.",
        detected_language="en",
        language_probability=0.98,
        audio_duration=60.0,
        elapsed_time=2.5,
        polished_text="Welcome to the interview. Thank you for inviting me today.",
        llm_model_used="deepseek-v4.1-flash",
    )
    return track_info, slice_cfg, tx_cfg, result


def test_export_transcript_to_txt(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()
    out_file = tmp_path / "transcript.txt"

    res_path = export_transcript_to_txt(out_file, track_info, slice_cfg, tx_cfg, result)
    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")

    assert "AUDIO TRANSCRIPTION" in content
    assert "interview.mp3" in content
    assert "POLISHED TRANSCRIPT (deepseek-v4.1-flash)" in content
    assert "Thank you for inviting me today." in content
    assert "Welcome to the interview." in content


def test_export_transcript_to_md(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()
    out_file = tmp_path / "transcript.md"

    res_path = export_transcript_to_md(out_file, track_info, slice_cfg, tx_cfg, result)
    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")

    assert "# Audio Transcription" in content
    assert "| **Source File** | `interview.mp3` |" in content
    assert "## Polished Transcript (deepseek-v4.1-flash)" in content
    assert "## Detailed Transcript" in content
    assert "- **`[00:10 -> 00:15]`** Welcome to the interview." in content


def test_export_transcript_to_pdf(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()
    out_file = tmp_path / "transcript.pdf"

    res_path = export_transcript_to_pdf(out_file, track_info, slice_cfg, tx_cfg, result)
    assert res_path.exists()
    assert res_path.stat().st_size > 1000  # Valid rendered PDF


def test_export_transcript_dispatcher(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()

    for fmt in ["docx", "pdf", "md", "txt"]:
        target = tmp_path / f"export.{fmt}"
        out = export_transcript(fmt, target, track_info, slice_cfg, tx_cfg, result)
        assert out.exists()
        assert out.stat().st_size > 0

    try:
        export_transcript("invalid_format", tmp_path / "invalid", track_info, slice_cfg, tx_cfg, result)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unsupported export format" in str(e)
