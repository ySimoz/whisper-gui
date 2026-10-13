"""Audio probing and ffmpeg trimming utilities."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from whisper_gui.models import AudioInfo

FFMPEG_CMD = "ffmpeg"
FFPROBE_CMD = "ffprobe"
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


def check_ffmpeg_installed() -> tuple[bool, str]:
    """Check if both ffmpeg and ffprobe are available and executable."""
    try:
        ffmpeg_res = subprocess.run(
            [FFMPEG_CMD, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if ffmpeg_res.returncode != 0:
            return False, f"ffmpeg returned error code {ffmpeg_res.returncode}"

        ffprobe_res = subprocess.run(
            [FFPROBE_CMD, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if ffprobe_res.returncode != 0:
            return False, f"ffprobe returned error code {ffprobe_res.returncode}"

        first_line = ffmpeg_res.stdout.splitlines()[0] if ffmpeg_res.stdout else "ffmpeg available"
        return True, first_line
    except FileNotFoundError as exc:
        return False, f"ffmpeg / ffprobe not found on PATH: {exc}"
    except Exception as exc:
        return False, f"Error checking ffmpeg: {exc}"


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

    cmd = [
        FFPROBE_CMD,
        "-v", "error",
        "-show_entries", "format=duration,format_name,size,bit_rate",
        "-show_streams",
        "-select_streams", "a:0",
        "-of", "json",
        str(path),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", check=True)
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
    cmd: list[str] = [FFMPEG_CMD, "-y"]

    # Accurate seeking: put -ss before -i for fast seek, but when precision is desired,
    # -ss before -i with ffmpeg 5+ is both frame-accurate and fast.
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

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        start_new_session=True,
    )

    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=STOP_CHECK_INTERVAL)
                break
            except subprocess.TimeoutExpired:
                if should_stop is not None and should_stop():
                    _kill_process_group(process)
                    process.communicate()
                    # Clean up partial output
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
            _kill_process_group(process)


def _kill_process_group(process: subprocess.Popen, grace: float = TERMINATE_GRACE_PERIOD) -> None:
    """Terminate the process group cleanly."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.time() + grace
    while time.time() < deadline:
        if process.poll() is not None:
            return
        time.sleep(0.05)

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1.0)
    except Exception:
        pass
