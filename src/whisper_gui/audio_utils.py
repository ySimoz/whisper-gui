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


def extract_waveform_peaks(
    file_path: str | Path,
    num_bins: int = 160,
    should_cancel: Callable[[], bool] | None = None,
) -> list[float]:
    """Decode an audio file with PyAV and return normalized peak amplitudes in [0.0, 1.0].

    Uses bounded-memory streaming chunk reduction so long recordings stay lightweight.
    Returns an empty list if the file cannot be read, contains no audio stream, or is cancelled.
    """
    if num_bins <= 0:
        return []

    path = Path(file_path)
    if not path.is_file():
        return []

    try:
        import av
        import numpy as np
    except ImportError:
        return []

    max_buf = max(num_bins * 32, 2048)
    block_size = 256
    sub_peaks: list[float] = []
    pending_max = 0.0
    pending_count = 0

    def _push_samples(flat: "np.ndarray") -> None:
        nonlocal block_size, sub_peaks, pending_max, pending_count
        if flat.size == 0:
            return
        abs_vals = np.abs(flat)
        idx = 0
        total = abs_vals.size

        if pending_count > 0:
            need = min(block_size - pending_count, total)
            if need > 0:
                pending_max = max(pending_max, float(abs_vals[:need].max()))
                pending_count += need
                idx += need
            if pending_count >= block_size:
                sub_peaks.append(pending_max)
                pending_max = 0.0
                pending_count = 0

        rem = total - idx
        if rem >= block_size:
            full_blocks = rem // block_size
            end = idx + full_blocks * block_size
            reshaped = abs_vals[idx:end].reshape(full_blocks, block_size)
            sub_peaks.extend(reshaped.max(axis=1).tolist())
            idx = end

        if idx < total:
            pending_max = max(pending_max, float(abs_vals[idx:].max()))
            pending_count = total - idx

        while len(sub_peaks) >= max_buf:
            even_len = (len(sub_peaks) // 2) * 2
            arr = np.asarray(sub_peaks[:even_len], dtype=np.float32).reshape(-1, 2)
            folded = arr.max(axis=1).tolist()
            if even_len < len(sub_peaks):
                folded.append(sub_peaks[-1])
            sub_peaks = folded
            block_size *= 2

    try:
        with av.open(str(path)) as container:
            audio_stream = next((s for s in container.streams if s.type == "audio"), None)
            if audio_stream is None:
                return []

            resampler = av.AudioResampler(format="flt", layout="mono")
            for frame in container.decode(audio_stream):
                if should_cancel is not None and should_cancel():
                    return []
                for resampled in resampler.resample(frame):
                    arr = resampled.to_ndarray()
                    _push_samples(arr.ravel())

            for resampled in resampler.resample(None):
                if should_cancel is not None and should_cancel():
                    return []
                arr = resampled.to_ndarray()
                _push_samples(arr.ravel())
    except Exception:
        return []

    if pending_count > 0:
        sub_peaks.append(pending_max)

    if not sub_peaks:
        return []

    peaks_arr = np.asarray(sub_peaks, dtype=np.float32)
    global_max = float(peaks_arr.max())
    if global_max <= 0.0:
        return [0.0] * num_bins

    if peaks_arr.size >= num_bins:
        bins = [float(seg.max()) / global_max for seg in np.array_split(peaks_arr, num_bins)]
    else:
        src_x = np.linspace(0.0, 1.0, peaks_arr.size)
        dst_x = np.linspace(0.0, 1.0, num_bins)
        interp = np.interp(dst_x, src_x, peaks_arr) / global_max
        bins = [float(v) for v in interp]

    return [max(0.0, min(1.0, v)) for v in bins]
