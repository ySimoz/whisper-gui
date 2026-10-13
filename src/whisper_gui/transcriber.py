"""Faster-Whisper model loading and streaming transcription."""

from __future__ import annotations

import gc
import os
import time
from collections.abc import Callable
from pathlib import Path

from faster_whisper import WhisperModel

from whisper_gui.audio_utils import CancelledError
from whisper_gui.models import TranscriptSegment, TranscriptionConfig, TranscriptionResult


class Transcriber:
    """Manages the faster-whisper model and streaming transcription execution."""

    def __init__(self) -> None:
        self._current_model: WhisperModel | None = None
        self._cached_config_key: tuple[str, str, str, int] | None = None

    def get_or_load_model(
        self,
        model_name: str,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 6,
        on_status: Callable[[str], None] | None = None,
    ) -> WhisperModel:
        """Returns cached model if matching configuration, or loads/downloads it."""
        key = (model_name, device, compute_type, cpu_threads)
        if self._current_model is not None and self._cached_config_key == key:
            return self._current_model

        if on_status is not None:
            on_status(f"Loading Whisper model '{model_name}' on {device} ({compute_type})...")

        # Free previous model memory if any
        self._current_model = None
        gc.collect()

        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
        )

        self._current_model = model
        self._cached_config_key = key
        return model

    def unload_model(self) -> None:
        """Unload active model to free RAM."""
        self._current_model = None
        self._cached_config_key = None
        gc.collect()

    def transcribe(
        self,
        audio_file: str | Path,
        config: TranscriptionConfig,
        slice_duration: float,
        on_segment: Callable[[TranscriptSegment], None] | None = None,
        on_progress: Callable[[float, float], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        """Execute transcription on audio_file and stream segments.

        Args:
            audio_file: Path to audio file to transcribe (e.g. the 16kHz mono WAV slice).
            config: Transcription settings.
            slice_duration: Anticipated length of this audio slice in seconds.
            on_segment: Callback invoked for each new transcribed segment.
            on_progress: Callback invoked with (current_audio_time_sec, total_slice_sec).
            on_status: Callback invoked with human-readable status text.
            should_stop: Callback checked periodically; aborts if returning True.

        Returns:
            TranscriptionResult with all segments, full text, and metrics.
        """
        model = self.get_or_load_model(
            model_name=config.model_name,
            device=config.device,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            on_status=on_status,
        )

        if should_stop is not None and should_stop():
            raise CancelledError("Transcription cancelled before starting")

        if on_status is not None:
            on_status("Transcribing audio...")

        start_time = time.time()
        audio_path_str = str(Path(audio_file).resolve())

        # Begin transcription generator
        segments_gen, info = model.transcribe(
            audio_path_str,
            language=config.language if config.language else None,
            beam_size=config.beam_size,
            vad_filter=config.vad_filter,
            condition_on_previous_text=False,
        )

        if on_status is not None:
            on_status(f"Transcribing (Language: {info.language}, prob: {info.language_probability:.2f})...")

        recorded_segments: list[TranscriptSegment] = []
        full_text_pieces: list[str] = []
        effective_duration = info.duration if info.duration > 0 else slice_duration

        for raw_seg in segments_gen:
            if should_stop is not None and should_stop():
                raise CancelledError("Transcription stopped by user")

            text_clean = raw_seg.text.strip()
            seg_obj = TranscriptSegment(
                start=raw_seg.start,
                end=raw_seg.end,
                text=text_clean,
            )
            recorded_segments.append(seg_obj)
            if text_clean:
                full_text_pieces.append(text_clean)

            if on_segment is not None:
                on_segment(seg_obj)

            if on_progress is not None and effective_duration > 0:
                on_progress(raw_seg.end, effective_duration)

        elapsed = time.time() - start_time
        full_text = " ".join(full_text_pieces)

        if on_progress is not None and effective_duration > 0:
            on_progress(effective_duration, effective_duration)

        return TranscriptionResult(
            segments=recorded_segments,
            full_text=full_text,
            detected_language=info.language,
            language_probability=info.language_probability,
            audio_duration=effective_duration,
            elapsed_time=elapsed,
            docx_path=None,
        )
