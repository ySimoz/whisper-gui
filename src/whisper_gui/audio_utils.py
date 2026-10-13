"""Audio probing and ffmpeg trimming utilities with cross-platform binary resolution and process management."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from whisper_gui.models import AudioInfo
from whisper_gui.platform_utils import (
    find_binary,
    get_subprocess_creation_flags,
    terminate_process_cross_platform,
)

STOP_CHECK_INTERVAL = 0.15
TERMINATE_GRACE_PERIOD = 2.0


class AudioError(Exception):
    """Base exception for audio processing errors."""


class AudioProbeError(AudioError):
    """Failed to probe audio file metadata."""


class AudioSliceError(AudioError):
    """Failed to slice audio with ffmpeg."""


class CancelledError(AudioError):
    """Operation was cancelled by user."""


def get_ffmpeg_cmd() -> str:
    """Return resolved path to ffmpeg binary across bundled, app-local, or system PATH."""
    found = find_binary("ffmpeg")
    return found if found else "ffmpeg"


def get_ffprobe_cmd() -> str:
    """Return resolved path to ffprobe binary across bundled, app-local, or system PATH."""
    found = find_binary("ffprobe")
    return found if found else "ffprobe"


def check_ffmpeg_installed() -> tuple[bool, str]:
    """Check if both ffmpeg and ffprobe are available and executable on this operating system."""
    ffmpeg_bin = get_ffmpeg_cmd()
    ffprobe_bin = get_ffprobe_cmd()
    flags = get_subprocess_creation_flags()

    try:
        ffmpeg_res = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            **flags,
        )
        if ffmpeg_res.returncode != 0:
            return False, f"ffmpeg ({ffmpeg_bin}) returned error code {ffmpeg_res.returncode}"

        ffprobe_res = subprocess.run(
            [ffprobe_bin, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            **flags,
        )
        if ffprobe_res.returncode != 0:
            return False, f"ffprobe ({ffprobe_bin}) returned error code {ffprobe_res.returncode}"

        first_line = ffmpeg_res.stdout.splitlines()[0] if ffmpeg_res.stdout else "ffmpeg available"
        return True, f"{first_line} [{ffmpeg_bin}]"
    except FileNotFoundError as exc:
        return False, f"ffmpeg / ffprobe not found: {exc}"
    except Exception as exc:
        return False, f"Error verifying ffmpeg binaries: {exc}"


def format_seconds(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    s = max(0.0, seconds)
    total_secs = int(round(s))
    hours = total_secs // 3600
    mins = (total_secs % 3600) // 60
    secs = total_secs % 60
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def parse_time_str(time_str: str) -> float:
    """Parse time string like '01:23:45' or '12:34' or '90' into seconds."""
    s = time_str.strip()
    if not s:
        return 0.0

    parts = s.split(":")
    try:
        if len(parts) == 3:
            h = float(parts[0])
            m = float(parts[1])
            sec = float(parts[2])
            return h * 3600 + m * 60 + sec
        elif len(parts) == 2:
            m = float(parts[0])
            sec = float(parts[1])
            return m * 60 + sec
        elif len(parts) == 1:
            return float(parts[0])
        else:
            raise ValueError(f"Unrecognized time format: '{time_str}'")
    except ValueError as exc:
        raise ValueError(f"Could not parse '{time_str}' as time: {exc}") from exc


def get_audio_info(file_path: str | Path) -> AudioInfo:
    """Probe audio file using ffprobe and return an AudioInfo object."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise AudioProbeError(f"File not found: {path}")

    ffprobe_bin = get_ffprobe_cmd()
    flags = get_subprocess_creation_flags()

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration,format_name,size,bit_rate",
        "-show_streams",
        "-select_streams", "a:0",
        "-of", "json",
        str(path),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=True, **flags)
        data = json.loads(res.stdout)
    except subprocess.CalledProcessError as exc:
        raise AudioProbeError(f"ffprobe failed for '{path.name}': {exc.stderr.strip()}") from exc
    except (json.JSONDecodeError, OSError) as exc:
        raise AudioProbeError(f"Failed to read metadata for '{path.name}': {exc}") from exc

    fmt_info = data.get("format", {})
    streams = data.get("streams", [])

    duration_str = fmt_info.get("duration")
    if not duration_str and streams:
        duration_str = streams[0].get("duration")

    if not duration_str:
        raise AudioProbeError(f"Could not determine audio duration for '{path.name}'")

    try:
        duration = float(duration_str)
    except ValueError as exc:
        raise AudioProbeError(f"Invalid duration '{duration_str}' for '{path.name}'") from exc

    sample_rate = 44100
    channels = 2
    if streams:
        st = streams[0]
        sample_rate = int(st.get("sample_rate", 44100))
        channels = int(st.get("channels", 2))

    size_bytes = int(fmt_info.get("size", path.stat().st_size if path.exists() else 0))
    bit_rate = int(fmt_info.get("bit_rate", 0))

    return AudioInfo(
        path=path,
        filename=path.name,
        duration=duration,
        format_name=fmt_info.get("format_name", path.suffix.lstrip(".")),
        sample_rate=sample_rate,
        channels=channels,
        bit_rate=bit_rate,
        size_bytes=size_bytes,
    )


def slice_audio(
    input_path: str | Path,
    output_path: str | Path,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Path:
    """Slice and convert an audio file to 16kHz mono WAV using ffmpeg.

    Args:
        input_path: Path to original audio file.
        output_path: Destination path for output wav file.
        start_sec: Offset in seconds from which to start slice.
        end_sec: Ending offset in seconds (None or <= 0 cuts to end of file).
        should_stop: Optional callable returning True to abort.

    Returns:
        Path to generated wav slice.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    start_sec = max(0.0, start_sec)
    if should_stop is not None and should_stop():
        raise CancelledError("Audio slicing cancelled before start")

    ffmpeg_bin = get_ffmpeg_cmd()
    cmd: list[str] = [ffmpeg_bin, "-y"]

    # Accurate seeking: -ss before -i is fast and accurate in ffmpeg 5+
    cmd.extend(["-ss", f"{start_sec:.3f}"])

    if end_sec is not None and end_sec > start_sec:
        duration = end_sec - start_sec
        cmd.extend(["-t", f"{duration:.3f}"])

    cmd.extend([
        "-i", str(in_p),
        "-vn",                    # Strip video track
        "-acodec", "pcm_s16le",    # 16-bit PCM WAV
        "-ar", "16000",           # 16kHz sample rate optimal for Whisper
        "-ac", "1",               # Mono channel
        str(out_p),
    ])

    flags = get_subprocess_creation_flags()
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        **flags,
    )

    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=STOP_CHECK_INTERVAL)
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    terminate_process_cross_platform(process)
                    process.communicate()
                    # Clean up partial output
                    if out_p.exists():
                        try:
                            out_p.unlink()
                        except OSError:
                            pass
                    raise CancelledError("Audio slicing cancelled by user")

        if should_stop is not None and should_stop():
            if out_p.exists():
                try:
                    out_p.unlink()
                except OSError:
                    pass
            raise CancelledError("Audio slicing cancelled by user")

        if process.returncode != 0:
            err = stderr.strip() if stderr else f"Exit code {process.returncode}"
            raise AudioSliceError(f"ffmpeg failed to slice audio: {err}")

        if not out_p.exists() or out_p.stat().st_size == 0:
            raise AudioSliceError("ffmpeg finished but output file is empty or missing")

        return out_p
    finally:
        if process.poll() is None:
            terminate_process_cross_platform(process)
