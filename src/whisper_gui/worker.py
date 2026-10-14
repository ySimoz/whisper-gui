"""Background QThread worker for non-blocking ffmpeg slicing and Whisper transcription."""

from __future__ import annotations

import logging
import os
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from whisper_gui.audio_utils import CancelledError, slice_audio
from whisper_gui.docx_exporter import export_transcript_to_docx
from whisper_gui.llm_cleaner import load_instructions, polish_transcript
from whisper_gui.models import AudioTrack, TrackStatus, TranscriptSegment, TranscriptionConfig, TranscriptionResult
from whisper_gui.transcriber import Transcriber

logger = logging.getLogger(__name__)


class TranscriptionWorker(QThread):
    """Background thread that executes audio slicing, transcription, and .docx export."""

    track_started = Signal(str)                          # track_id
    status_updated = Signal(str, str)                    # track_id, message
    segment_received = Signal(str, object)               # track_id, TranscriptSegment
    progress_updated = Signal(str, int, str)             # track_id, percent (0-100), time_str
    track_completed = Signal(str, object)                # track_id, TranscriptionResult
    track_error = Signal(str, str)                       # track_id, error_message
    batch_finished = Signal()
    cancelled = Signal()

    def __init__(
        self,
        tracks: list[AudioTrack],
        transcription_config: TranscriptionConfig,
        transcriber: Transcriber,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.tracks = tracks
        self.config = transcription_config
        self.transcriber = transcriber
        self._is_cancelled = False
        self._current_temp_wav: Path | None = None

    def request_stop(self) -> None:
        """Signal the worker to stop processing."""
        self._is_cancelled = True

    def should_stop(self) -> bool:
        """Check if stop was requested."""
        return self._is_cancelled

    def run(self) -> None:
        """Main thread loop running through queued tracks."""
        try:
            for track in self.tracks:
                if self.should_stop():
                    self.status_updated.emit(track.id, "Transcription stopped")
                    track.status = TrackStatus.CANCELLED
                    self.cancelled.emit()
                    return

                self._process_single_track(track)

            if not self.should_stop():
                self.batch_finished.emit()
        except Exception as exc:
            # Catch unexpected top-level thread errors
            traceback.print_exc()

    def _process_single_track(self, track: AudioTrack) -> None:
        """Process one audio track from slicing to docx export."""
        track.status = TrackStatus.SLICING
        self.track_started.emit(track.id)

        # 1. Determine time slice boundaries
        total_duration = track.info.duration
        slice_cfg = track.slice_config
        start_sec = max(0.0, slice_cfg.start_sec)
        end_sec = slice_cfg.effective_end(total_duration)
        slice_duration = slice_cfg.effective_duration(total_duration)

        # Setup temporary file for sliced audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            temp_wav_path = Path(tmp.name)
        self._current_temp_wav = temp_wav_path

        try:
            # 2. Slice audio with ffmpeg
            self.status_updated.emit(track.id, "Slicing audio with ffmpeg...")
            slice_audio(
                input_path=track.file_path,
                output_path=temp_wav_path,
                start_sec=start_sec,
                end_sec=end_sec,
                should_stop=self.should_stop,
            )

            if self.should_stop():
                track.status = TrackStatus.CANCELLED
                self.cancelled.emit()
                return

            # 3. Transcribe with faster-whisper
            track.status = TrackStatus.TRANSCRIBING
            self.status_updated.emit(track.id, f"Transcribing with {self.config.model_name}...")

            def handle_segment(seg: TranscriptSegment) -> None:
                self.segment_received.emit(track.id, seg)

            def handle_progress(current_sec: float, total_sec: float) -> None:
                if total_sec > 0:
                    pct = min(100, int((current_sec / total_sec) * 100))
                    msg = f"{current_sec:.1f}s / {total_sec:.1f}s ({pct}%)"
                    self.progress_updated.emit(track.id, pct, msg)

            def handle_status(msg: str) -> None:
                self.status_updated.emit(track.id, msg)

            result = self.transcriber.transcribe(
                audio_file=temp_wav_path,
                config=self.config,
                slice_duration=slice_duration,
                on_segment=handle_segment,
                on_progress=handle_progress,
                on_status=handle_status,
                should_stop=self.should_stop,
            )

            if self.should_stop():
                track.status = TrackStatus.CANCELLED
                self.cancelled.emit()
                return

            # 3.5 Optional LLM Polishing
            llm_cfg = self.config.llm_config
            if llm_cfg.enabled and llm_cfg.api_key.strip():
                try:
                    self.status_updated.emit(
                        track.id, f"Polishing transcript with {llm_cfg.model_name}..."
                    )
                    instructions_text, source_name = load_instructions(llm_cfg)
                    result.llm_model_used = llm_cfg.model_name
                    result.llm_instructions_name = source_name

                    polished = polish_transcript(
                        raw_text=result.full_text,
                        config=llm_cfg,
                        instructions=instructions_text,
                        cancel_check=self.should_stop,
                    )
                    result.polished_text = polished
                    self.status_updated.emit(track.id, "Transcript polished successfully.")
                except InterruptedError:
                    track.status = TrackStatus.CANCELLED
                    self.cancelled.emit()
                    return
                except Exception as llm_err:
                    logger.warning("LLM polishing failed: %s", llm_err)
                    result.llm_error = str(llm_err)
                    self.status_updated.emit(
                        track.id, f"LLM polish warning: {llm_err} (exporting raw transcript)"
                    )

            if self.should_stop():
                track.status = TrackStatus.CANCELLED
                self.cancelled.emit()
                return

            # 4. Export to .docx
            self.status_updated.emit(track.id, "Exporting Word (.docx) document...")
            dest_docx = track.effective_docx_path(self.config.output_dir)

            final_docx_path = export_transcript_to_docx(
                output_path=dest_docx,
                track_info=track.info,
                slice_config=slice_cfg,
                transcription_config=self.config,
                result=result,
            )

            result.docx_path = final_docx_path
            track.result = result
            track.output_docx_path = final_docx_path
            track.status = TrackStatus.COMPLETED
            track.progress_percent = 100
            track.status_message = f"Completed ({result.speed_factor:.1f}x real-time)"

            self.status_updated.emit(track.id, f"Saved document to {final_docx_path.name}")
            self.track_completed.emit(track.id, result)

        except CancelledError:
            track.status = TrackStatus.CANCELLED
            track.status_message = "Cancelled"
            self.status_updated.emit(track.id, "Cancelled by user")
            self.cancelled.emit()

        except Exception as exc:
            track.status = TrackStatus.ERROR
            err_msg = str(exc)
            track.error_message = err_msg
            track.status_message = f"Error: {err_msg}"
            self.track_error.emit(track.id, err_msg)

        finally:
            # Clean up temporary WAV slice
            if self._current_temp_wav and self._current_temp_wav.exists():
                try:
                    self._current_temp_wav.unlink()
                except OSError:
                    pass
            self._current_temp_wav = None
