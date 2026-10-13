"""Data models for audio tracks, slicing settings, transcription results, and status."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SliceMode(str, Enum):
    FULL = "full"
    RANGE = "range"
    PRESET = "preset"


class TrackStatus(str, Enum):
    QUEUED = "Queued"
    SLICING = "Slicing Audio"
    TRANSCRIBING = "Transcribing"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    ERROR = "Error"


@dataclass
class AudioInfo:
    """Metadata for an imported audio file extracted via ffprobe."""

    path: Path
    filename: str
    duration: float  # seconds
    format_name: str = "audio"
    sample_rate: int = 44100
    channels: int = 2
    bit_rate: int = 0
    size_bytes: int = 0

    @property
    def duration_formatted(self) -> str:
        """Format total duration as HH:MM:SS."""
        total_secs = int(round(self.duration))
        hours = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


@dataclass
class SliceConfig:
    """Configuration for ffmpeg audio length and range slicing."""

    mode: SliceMode = SliceMode.FULL
    start_sec: float = 0.0
    end_sec: float | None = None  # None indicates slice up to the very end of file

    def effective_end(self, total_duration: float) -> float:
        """Return the actual ending point in seconds."""
        if self.end_sec is None or self.end_sec <= 0 or self.end_sec > total_duration:
            return total_duration
        return max(self.start_sec, self.end_sec)

    def effective_duration(self, total_duration: float) -> float:
        """Calculates the duration of the audio slice that will be transcribed."""
        end = self.effective_end(total_duration)
        start = max(0.0, min(self.start_sec, total_duration))
        return max(0.0, end - start)

    def is_full(self, total_duration: float) -> bool:
        """Returns True if the entire audio track will be transcribed without trimming."""
        if self.mode == SliceMode.FULL:
            return True
        eff_start = max(0.0, self.start_sec)
        eff_end = self.effective_end(total_duration)
        return eff_start == 0.0 and abs(eff_end - total_duration) < 0.1


@dataclass
class TranscriptSegment:
    """One transcribed segment produced by Whisper."""

    start: float  # Start time in seconds (relative to slice)
    end: float    # End time in seconds (relative to slice)
    text: str

    @property
    def formatted_timerange(self) -> str:
        """Format range as [HH:MM:SS -> HH:MM:SS] or [MM:SS -> MM:SS]."""
        return f"[{self._format_sec(self.start)} -> {self._format_sec(self.end)}]"

    @staticmethod
    def _format_sec(seconds: float) -> str:
        s = max(0.0, seconds)
        mins = int(s // 60)
        secs = int(s % 60)
        hours = mins // 60
        mins = mins % 60
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"


@dataclass
class TranscriptionConfig:
    """Options for the faster-whisper model and export."""

    model_name: str = "large-v3-turbo"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 6
    language: str | None = None  # None for auto-detection
    vad_filter: bool = True
    beam_size: int = 5
    include_timestamps_in_docx: bool = True
    output_dir: Path | None = None


@dataclass
class TranscriptionResult:
    """Final result of a completed transcription."""

    segments: list[TranscriptSegment] = field(default_factory=list)
    full_text: str = ""
    detected_language: str = ""
    language_probability: float = 0.0
    audio_duration: float = 0.0  # Duration of the transcribed slice
    elapsed_time: float = 0.0     # Time taken to transcribe
    docx_path: Path | None = None

    @property
    def speed_factor(self) -> float:
        """Ratio of audio length to transcription time (e.g. 3.2x real-time speed)."""
        if self.elapsed_time > 0:
            return self.audio_duration / self.elapsed_time
        return 0.0


class AudioTrack:
    """Represents an audio track queued or loaded in the GUI."""

    def __init__(self, file_path: Path | str, info: AudioInfo) -> None:
        self.id: str = str(uuid.uuid4())
        self.file_path: Path = Path(file_path).resolve()
        self.info: AudioInfo = info
        self.slice_config: SliceConfig = SliceConfig(
            mode=SliceMode.FULL,
            start_sec=0.0,
            end_sec=info.duration,
        )
        self.status: TrackStatus = TrackStatus.QUEUED
        self.progress_percent: int = 0
        self.status_message: str = "Ready"
        self.result: TranscriptionResult | None = None
        self.error_message: str | None = None
        self.output_docx_path: Path | None = None

    @property
    def default_docx_path(self) -> Path:
        """Default path for the generated .docx file alongside the audio file."""
        stem = self.file_path.stem
        parent = self.file_path.parent
        return parent / f"{stem}_transcript.docx"

    def effective_docx_path(self, target_dir: Path | None = None) -> Path:
        """Returns the destination .docx path given an optional target directory."""
        if self.output_docx_path:
            return self.output_docx_path
        if target_dir:
            return target_dir / f"{self.file_path.stem}_transcript.docx"
        return self.default_docx_path
