"""Faster-Whisper model loading, disk caching, RAM management, and streaming transcription."""

from __future__ import annotations

import gc
import io
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from faster_whisper import WhisperModel
from tqdm import tqdm as _base_tqdm

from whisper_gui.audio_utils import CancelledError
from whisper_gui.i18n import tr
from whisper_gui.models import TranscriptSegment, TranscriptionConfig, TranscriptionResult

_MODEL_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]

MODEL_RAM_ESTIMATES = {
    "large-v3-turbo": 1500,
    "large-v3": 3000,
    "medium": 1500,
    "small": 500,
    "base": 200,
    "tiny": 75,
}


def resolve_model_repo_id(model_name: str) -> str:
    """Resolve a Whisper model size alias to its HuggingFace repository ID."""
    if re.match(r".*/.*", model_name):
        return model_name
    from faster_whisper.utils import _MODELS

    return _MODELS.get(model_name, model_name)


def estimate_model_ram_mb(model_name: str) -> int:
    """Return estimated RAM usage in MB for the model when loaded."""
    return MODEL_RAM_ESTIMATES.get(model_name, 1000)


def get_model_cache_dir(model_name: str) -> Path | None:
    """Resolve the HuggingFace cache directory path for the given Whisper model."""
    if not model_name or not model_name.strip():
        return None
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub.constants import HF_HUB_CACHE

        repo_id = _MODELS.get(model_name, model_name)
        folder_name = "models--" + repo_id.replace("/", "--")
        return Path(HF_HUB_CACHE) / folder_name
    except Exception:
        return None


def is_model_downloaded_on_disk(model_name: str) -> bool:
    """Check if the given Whisper model is already stored locally on disk in HuggingFace cache."""
    try:
        local_dir = get_model_cache_dir(model_name)
        if local_dir is not None and local_dir.is_dir():
            snapshots = local_dir / "snapshots"
            if snapshots.is_dir() and any(snapshots.iterdir()):
                return True
        return False
    except Exception:
        return False


def get_model_cache_size_mb(model_name: str) -> float:
    """Return total size on disk in MB for the cached model directory."""
    cache_dir = get_model_cache_dir(model_name)
    if cache_dir is None or not cache_dir.is_dir():
        return 0.0
    total_bytes = 0
    try:
        for entry in cache_dir.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                total_bytes += entry.stat().st_size
    except OSError:
        return 0.0
    return round(total_bytes / (1024 * 1024), 2)


def delete_cached_model(model_name: str) -> bool:
    """Safely delete the cached model directory from HuggingFace cache."""
    cache_dir = get_model_cache_dir(model_name)
    if cache_dir is None or not cache_dir.is_dir() or cache_dir.is_symlink():
        return False
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        cache_root = Path(HF_HUB_CACHE).resolve()
        resolved = cache_dir.resolve()
        if resolved.parent != cache_root or not resolved.name.startswith("models--"):
            return False
        shutil.rmtree(resolved)
        return True
    except OSError:
        return False


class _SnapshotProgressTracker:
    """Thread-safe byte progress aggregator for HuggingFace snapshot_download."""

    def __init__(
        self,
        model_name: str,
        on_progress: Callable[[int, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.model_name = model_name
        self.on_progress = on_progress
        self.on_status = on_status
        self.should_stop = should_stop
        self._lock = threading.Lock()
        self._transfer_n = 0
        self._transfer_total = 0
        self._reconstruct_n = 0
        self._reconstruct_total = 0
        self._last_emit_time = 0.0
        self._last_emit_pct = -2

    def check_cancelled(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise CancelledError("Model download cancelled by user")

    def update_bar(self, name: str, n: int, total: int | None, force: bool = False) -> None:
        self.check_cancelled()
        with self._lock:
            if name == "huggingface_hub.snapshot_download.transfer":
                self._transfer_n = max(self._transfer_n, int(n or 0))
                if total is not None and total > 0:
                    self._transfer_total = max(self._transfer_total, int(total))
            elif name == "huggingface_hub.snapshot_download":
                self._reconstruct_n = max(self._reconstruct_n, int(n or 0))
                if total is not None and total > 0:
                    self._reconstruct_total = max(self._reconstruct_total, int(total))
            else:
                return

            total_bytes = max(self._reconstruct_total, self._transfer_total)
            done_bytes = max(self._transfer_n, self._reconstruct_n)
            if total_bytes > 0:
                done_bytes = min(done_bytes, total_bytes)
                pct = min(100, int((done_bytes / total_bytes) * 100))
            else:
                pct = -1

            now = time.monotonic()
            if not force and pct == self._last_emit_pct and (now - self._last_emit_time) < 0.12:
                return
            if not force and (now - self._last_emit_time) < 0.08 and pct < 100:
                return

            self._last_emit_time = now
            self._last_emit_pct = pct

            done_mb = done_bytes / (1024 * 1024)
            total_mb = total_bytes / (1024 * 1024)

        if total_bytes > 0:
            metrics = f"{done_mb:.1f} / {total_mb:.1f} MB ({pct}%)"
            status = tr(
                "transcriber.downloading_progress",
                model=self.model_name,
                done_mb=done_mb,
                total_mb=total_mb,
                pct=pct,
            )
        elif done_bytes > 0:
            metrics = f"{done_mb:.1f} MB"
            status = tr(
                "transcriber.downloading_bytes",
                model=self.model_name,
                done_mb=done_mb,
            )
        else:
            metrics = tr("transcriber.downloading_preparing_short")
            status = tr("transcriber.downloading_preparing", model=self.model_name)

        if self.on_progress is not None:
            self.on_progress(pct, metrics)
        if self.on_status is not None:
            self.on_status(status)

    def make_tqdm_class(self):
        tracker = self

        class _ProgressTqdm(_base_tqdm):
            def __init__(self, *args, **kwargs):
                self._hf_name = kwargs.pop("name", "") or ""
                kwargs["disable"] = False
                kwargs.setdefault("file", io.StringIO())
                super().__init__(*args, **kwargs)
                if not self._hf_name:
                    desc = str(kwargs.get("desc", "") or "")
                    if "Downloading bytes" in desc:
                        self._hf_name = "huggingface_hub.snapshot_download.transfer"
                    elif "Reconstructing" in desc:
                        self._hf_name = "huggingface_hub.snapshot_download"

            def update(self, n=1):
                tracker.check_cancelled()
                res = super().update(n)
                tracker.update_bar(self._hf_name, int(self.n or 0), self.total)
                return res

            def refresh(self, nolock=False, lock_args=None):
                tracker.check_cancelled()
                res = super().refresh(nolock=nolock, lock_args=lock_args)
                tracker.update_bar(self._hf_name, int(self.n or 0), self.total)
                return res

            def close(self):
                try:
                    if self._hf_name:
                        tracker.update_bar(self._hf_name, int(self.n or 0), self.total, force=True)
                except CancelledError:
                    pass
                super().close()

        return _ProgressTqdm


def download_model_with_progress(
    model_name: str,
    on_progress: Callable[[int, str], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    local_files_only: bool = False,
) -> str:
    """Download or resolve a faster-whisper model from HuggingFace Hub with byte-level progress."""
    if os.path.isdir(model_name):
        return model_name

    if should_stop is not None and should_stop():
        raise CancelledError("Model download cancelled before starting")

    import huggingface_hub

    repo_id = resolve_model_repo_id(model_name)
    is_cached = is_model_downloaded_on_disk(model_name)

    if is_cached or local_files_only:
        try:
            return huggingface_hub.snapshot_download(
                repo_id,
                local_files_only=True,
                allow_patterns=_MODEL_ALLOW_PATTERNS,
            )
        except Exception:
            if local_files_only:
                raise

    if on_status is not None:
        on_status(tr("transcriber.downloading_preparing", model=model_name))
    if on_progress is not None:
        on_progress(-1, tr("transcriber.downloading_preparing_short"))

    tracker = _SnapshotProgressTracker(
        model_name=model_name,
        on_progress=on_progress,
        on_status=on_status,
        should_stop=should_stop,
    )
    tqdm_cls = tracker.make_tqdm_class()
    return huggingface_hub.snapshot_download(
        repo_id,
        local_files_only=False,
        allow_patterns=_MODEL_ALLOW_PATTERNS,
        tqdm_class=tqdm_cls,
    )


class Transcriber:
    """Manages the faster-whisper model, memory caching, and streaming transcription execution."""

    def __init__(self) -> None:
        self._current_model: WhisperModel | None = None
        self._cached_config_key: tuple[str, str, str, int] | None = None

    @property
    def is_loaded(self) -> bool:
        """Returns True if a model is currently resident in RAM."""
        return self._current_model is not None

    @property
    def loaded_model_name(self) -> str | None:
        """Returns the name of the model currently resident in RAM, or None."""
        if self._cached_config_key:
            return self._cached_config_key[0]
        return None

    def get_or_load_model(
        self,
        model_name: str,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 6,
        on_status: Callable[[str], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> WhisperModel:
        """Returns cached in-RAM model if configuration matches, or downloads and loads it."""
        # macOS compatibility: CTranslate2 on macOS uses CPU with Accelerate/NEON vectorization
        if sys.platform == "darwin" and device.lower() == "cuda":
            if on_status is not None:
                on_status(tr("transcriber.cuda_macos"))
            device = "cpu"
            if compute_type in ("float16", "int8_float16"):
                compute_type = "int8"

        key = (model_name, device, compute_type, cpu_threads)
        if self._current_model is not None and self._cached_config_key == key:
            return self._current_model

        if should_stop is not None and should_stop():
            raise CancelledError("Model load cancelled before starting")

        # Unload previous model before loading new one to avoid double RAM usage
        self.unload_model()

        is_cached = is_model_downloaded_on_disk(model_name)
        model_source: str = model_name
        if not os.path.isdir(model_name):
            if not is_cached:
                model_source = download_model_with_progress(
                    model_name=model_name,
                    on_progress=on_progress,
                    on_status=on_status,
                    should_stop=should_stop,
                )
            else:
                try:
                    model_source = download_model_with_progress(
                        model_name=model_name,
                        local_files_only=True,
                        should_stop=should_stop,
                    )
                except CancelledError:
                    raise
                except Exception:
                    model_source = model_name

        if should_stop is not None and should_stop():
            raise CancelledError("Model load cancelled before initializing weights")

        if on_status is not None:
            desc = tr("transcriber.source_disk") if (is_cached or os.path.isdir(model_source)) else tr("transcriber.source_hf")
            on_status(
                tr(
                    "transcriber.loading_model",
                    model=model_name,
                    source=desc,
                    device=device,
                    compute=compute_type,
                )
            )
        if on_progress is not None:
            on_progress(-1, tr("transcriber.loading_short", model=model_name))

        model = WhisperModel(
            model_source,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
        )

        self._current_model = model
        self._cached_config_key = key
        if on_progress is not None:
            on_progress(0, tr("transcriber.model_ready", model=model_name))
        return model

    def unload_model(self) -> None:
        """Unload active model from memory and explicitly invoke garbage collection to free RAM."""
        if self._current_model is not None:
            del self._current_model
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
        on_model_progress: Callable[[int, str], None] | None = None,
    ) -> TranscriptionResult:
        """Execute transcription on audio_file and stream segments."""
        model = self.get_or_load_model(
            model_name=config.model_name,
            device=config.device,
            compute_type=config.compute_type,
            cpu_threads=config.cpu_threads,
            on_status=on_status,
            on_progress=on_model_progress,
            should_stop=should_stop,
        )

        if should_stop is not None and should_stop():
            raise CancelledError("Transcription cancelled before starting")

        if on_status is not None:
            on_status(tr("transcriber.transcribing"))

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
            on_status(
                tr(
                    "transcriber.transcribing_lang",
                    lang=info.language,
                    prob=info.language_probability,
                )
            )

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
