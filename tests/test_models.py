"""Unit tests for whisper_gui models."""

from pathlib import Path
from whisper_gui.models import (
    AudioInfo,
    AudioTrack,
    SliceConfig,
    SliceMode,
    TrackStatus,
    TranscriptSegment,
    TranscriptionConfig,
    TranscriptionResult,
)


def test_audio_info_properties():
    info = AudioInfo(
        path=Path("/tmp/song.mp3"),
        filename="song.mp3",
        duration=3665.4,
        format_name="mp3",
        sample_rate=44100,
        channels=2,
        bit_rate=320000,
        size_bytes=10 * 1024 * 1024,
    )
    assert info.duration_formatted == "01:01:05"
    assert round(info.size_mb, 1) == 10.0


def test_slice_config_calculations():
    # Full mode
    cfg_full = SliceConfig(mode=SliceMode.FULL, start_sec=0.0, end_sec=None)
    assert cfg_full.effective_end(100.0) == 100.0
    assert cfg_full.effective_duration(100.0) == 100.0
    assert cfg_full.is_full(100.0) is True

    # Custom range mode: 10s to 40s
    cfg_range = SliceConfig(mode=SliceMode.RANGE, start_sec=10.0, end_sec=40.0)
    assert cfg_range.effective_end(100.0) == 40.0
    assert cfg_range.effective_duration(100.0) == 30.0
    assert cfg_range.is_full(100.0) is False

    # Out of bounds clamp: end > total
    cfg_oob = SliceConfig(mode=SliceMode.RANGE, start_sec=10.0, end_sec=200.0)
    assert cfg_oob.effective_end(100.0) == 100.0
    assert cfg_oob.effective_duration(100.0) == 90.0


def test_transcript_segment_formatting():
    seg1 = TranscriptSegment(start=75.0, end=82.5, text="Hello world")
    assert seg1.formatted_timerange == "[01:15 -> 01:22]"

    seg2 = TranscriptSegment(start=3665.0, end=3670.0, text="Long audio")
    assert seg2.formatted_timerange == "[01:01:05 -> 01:01:10]"


def test_transcription_result_speed_factor():
    res = TranscriptionResult(
        segments=[],
        full_text="Test",
        audio_duration=120.0,
        elapsed_time=30.0,
    )
    assert res.speed_factor == 4.0


def test_audio_track_defaults():
    info = AudioInfo(
        path=Path("/home/user/test.mp3"),
        filename="test.mp3",
        duration=60.0,
    )
    track = AudioTrack("/home/user/test.mp3", info)
    assert track.status == TrackStatus.QUEUED
    assert track.default_docx_path == Path("/home/user/test_transcript.docx")

    # Custom target dir
    target_dir = Path("/custom/output")
    assert track.effective_docx_path(target_dir) == Path("/custom/output/test_transcript.docx")
