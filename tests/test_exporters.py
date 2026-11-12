"""Unit tests for multi-format exporters (PDF, Markdown, Plain Text, DOCX)."""

from pathlib import Path

from whisper_gui.exporters import (
    export_transcript,
    export_transcript_to_docx,
    export_transcript_to_md,
    export_transcript_to_pdf,
    export_transcript_to_srt,
    export_transcript_to_txt,
    export_transcript_to_vtt,
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


def test_export_transcript_to_srt(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()
    out_file = tmp_path / "transcript.srt"

    res_path = export_transcript_to_srt(out_file, track_info, slice_cfg, tx_cfg, result)
    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")

    assert "1\n00:00:10,000 --> 00:00:15,000\nWelcome to the interview." in content
    assert "2\n00:00:15,500 --> 00:00:22,000\nThank you for having me today." in content


def test_export_transcript_to_srt_fallback_full_text(tmp_path: Path):
    result = TranscriptionResult(full_text="Single fallback line.", audio_duration=12.5)
    out_file = tmp_path / "fallback.srt"

    res_path = export_transcript_to_srt(out_file, result=result)
    content = res_path.read_text(encoding="utf-8")
    assert content == "1\n00:00:00,000 --> 00:00:12,500\nSingle fallback line.\n"


def test_export_transcript_to_vtt(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()
    out_file = tmp_path / "transcript.vtt"

    res_path = export_transcript_to_vtt(out_file, track_info, slice_cfg, tx_cfg, result)
    assert res_path.exists()
    content = res_path.read_text(encoding="utf-8")

    assert content.startswith("WEBVTT\n\n")
    assert "00:00:10.000 --> 00:00:15.000\nWelcome to the interview." in content
    assert "00:00:15.500 --> 00:00:22.000\nThank you for having me today." in content


def test_export_transcript_to_vtt_fallback_full_text(tmp_path: Path):
    result = TranscriptionResult(full_text="Single fallback VTT line.", audio_duration=8.25)
    out_file = tmp_path / "fallback.vtt"

    res_path = export_transcript_to_vtt(out_file, result=result)
    content = res_path.read_text(encoding="utf-8")
    assert content == "WEBVTT\n\n00:00:00.000 --> 00:00:08.250\nSingle fallback VTT line.\n"


def test_export_transcript_dispatcher(tmp_path: Path):
    track_info, slice_cfg, tx_cfg, result = _make_sample_data()

    for fmt in ["docx", "pdf", "md", "txt", "srt", "vtt"]:
        target = tmp_path / f"export.{fmt}"
        out = export_transcript(fmt, target, track_info, slice_cfg, tx_cfg, result)
        assert out.exists()
        assert out.stat().st_size > 0

    try:
        export_transcript("invalid_format", tmp_path / "invalid", track_info, slice_cfg, tx_cfg, result)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unsupported export format" in str(e)
