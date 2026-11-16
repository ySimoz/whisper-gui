"""Unit tests for audio_utils (ffprobe, ffmpeg slicing, cancellation)."""

import subprocess
import tempfile
from pathlib import Path
import pytest

from whisper_gui.audio_utils import (
    AudioProbeError,
    CancelledError,
    check_ffmpeg_installed,
    extract_waveform_peaks,
    format_seconds,
    get_audio_info,
    get_ffmpeg_cmd,
    parse_time_str,
    slice_audio,
)


@pytest.fixture
def sample_wav_path(tmp_path: Path) -> Path:
    """Generate a clean 5-second sine wave audio file using ffmpeg."""
    out_file = tmp_path / "sample_5s.wav"
    cmd = [
        get_ffmpeg_cmd(), "-y",
        "-f", "lavfi",
        "-i", "sine=frequency=440:duration=5",
        str(out_file),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_file


def test_format_seconds():
    assert format_seconds(0) == "00:00"
    assert format_seconds(45) == "00:45"
    assert format_seconds(125) == "02:05"
    assert format_seconds(3665) == "01:01:05"


def test_parse_time_str():
    assert parse_time_str("00:00:45") == 45.0
    assert parse_time_str("01:30") == 90.0
    assert parse_time_str("01:01:05") == 3665.0
    assert parse_time_str("120") == 120.0

    with pytest.raises(ValueError):
        parse_time_str("not_a_time")


def test_check_ffmpeg_installed():
    ok, msg = check_ffmpeg_installed()
    assert ok is True
    assert "ffmpeg" in msg.lower()


def test_get_audio_info(sample_wav_path: Path):
    info = get_audio_info(sample_wav_path)
    assert info.filename == "sample_5s.wav"
    assert abs(info.duration - 5.0) < 0.2
    assert info.channels in (1, 2)
    assert info.size_bytes > 0


def test_get_audio_info_nonexistent():
    with pytest.raises(AudioProbeError):
        get_audio_info(Path("/nonexistent/file.wav"))


def test_slice_audio_segment(sample_wav_path: Path, tmp_path: Path):
    out_slice = tmp_path / "slice_2s.wav"
    # Slice from 1.0s to 3.0s (duration = 2.0s)
    slice_audio(
        input_path=sample_wav_path,
        output_path=out_slice,
        start_sec=1.0,
        end_sec=3.0,
    )
    assert out_slice.exists()

    slice_info = get_audio_info(out_slice)
    assert abs(slice_info.duration - 2.0) < 0.2
    assert slice_info.sample_rate == 16000
    assert slice_info.channels == 1  # Converted to mono 16kHz for Whisper


def test_slice_audio_cancellation(sample_wav_path: Path, tmp_path: Path):
    out_slice = tmp_path / "slice_cancel.wav"
    with pytest.raises(CancelledError):
        slice_audio(
            input_path=sample_wav_path,
            output_path=out_slice,
            start_sec=0.0,
            end_sec=5.0,
            should_stop=lambda: True,  # Immediate stop
        )


def test_extract_waveform_peaks_valid_and_edge_cases(sample_wav_path: Path, tmp_path: Path):
    peaks = extract_waveform_peaks(sample_wav_path, num_bins=80)
    assert len(peaks) == 80
    assert all(0.0 <= p <= 1.0 for p in peaks)
    assert max(peaks) == pytest.approx(1.0)

    # Silent WAV produces all-zero bins without error
    silent_wav = tmp_path / "silent.wav"
    import wave

    with wave.open(str(silent_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)
    silent_peaks = extract_waveform_peaks(silent_wav, num_bins=40)
    assert silent_peaks == [0.0] * 40

    # Missing, corrupt, zero-bin, and cancelled cases fail gracefully
    assert extract_waveform_peaks(tmp_path / "missing.wav", num_bins=40) == []
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"not valid audio data")
    assert extract_waveform_peaks(corrupt, num_bins=40) == []
    assert extract_waveform_peaks(sample_wav_path, num_bins=0) == []
    assert extract_waveform_peaks(sample_wav_path, num_bins=40, should_cancel=lambda: True) == []
