"""Local transcript history persistence with test-safe isolation."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from whisper_gui.i18n import tr
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


def get_history_dir(base_dir: Path | str | None = None) -> Path:
    """Resolve the directory for local transcript history JSON files.

    Isolation order:
    1. Explicit ``base_dir`` argument
    2. ``WHISPER_GUI_HISTORY_DIR`` environment variable
    3. Per-test temporary directory when ``PYTEST_CURRENT_TEST`` is set
    4. Platform-standard application support directory
    """
    if base_dir is not None:
        return Path(base_dir).resolve()

    env_dir = os.environ.get("WHISPER_GUI_HISTORY_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()

    pytest_current = os.environ.get("PYTEST_CURRENT_TEST")
    if pytest_current:
        digest = hashlib.sha1(f"{os.getpid()}:{pytest_current}".encode("utf-8")).hexdigest()[:12]
        return Path(tempfile.gettempdir()) / "whisper_gui_pytest_history" / digest

    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "WhisperGUI"
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = (Path(appdata) if appdata else Path.home() / "AppData" / "Local") / "WhisperGUI"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        root = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "WhisperGUI"

    return root / "history"


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours = total // 3600
    mins = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


@dataclass
class HistoryEntry:
    """Serializable snapshot of a completed transcription for reopening without re-transcribing."""

    id: str
    created_at: str
    audio_path: str
    filename: str
    audio_duration: float = 0.0
    slice_start: float = 0.0
    slice_end: float | None = None
    model_name: str = ""
    language: str | None = None
    detected_language: str = ""
    language_probability: float = 0.0
    elapsed_time: float = 0.0
    full_text: str = ""
    polished_text: str | None = None
    llm_model_used: str | None = None
    llm_instructions_name: str | None = None
    raw_segments_stale: bool = False
    segments: list[TranscriptSegment] = field(default_factory=list)
    exports: dict[str, str] = field(default_factory=dict)

    def preview_text(self, max_len: int = 120) -> str:
        """Return a single-line excerpt prioritizing polished text over raw text."""
        source = (self.polished_text or "").strip() or (self.full_text or "").strip()
        if not source and self.segments:
            source = " ".join(s.text.strip() for s in self.segments if s.text.strip())
        normalized = " ".join(source.split())
        if len(normalized) <= max_len:
            return normalized
        return normalized[: max_len - 1].rstrip() + "…"

    def formatted_date(self) -> str:
        """Return compact YYYY-MM-DD HH:MM timestamp for display."""
        try:
            dt = datetime.datetime.fromisoformat(self.created_at)
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return self.created_at[:16].replace("T", " ")

    def formatted_duration(self) -> str:
        """Return tabular audio duration string."""
        return _format_duration(self.audio_duration)

    def to_dict(self) -> dict:
        """Serialize entry into a JSON-compatible dictionary."""
        return {
            "version": 1,
            "id": self.id,
            "created_at": self.created_at,
            "audio_path": self.audio_path,
            "filename": self.filename,
            "audio_duration": self.audio_duration,
            "slice_start": self.slice_start,
            "slice_end": self.slice_end,
            "model_name": self.model_name,
            "language": self.language,
            "detected_language": self.detected_language,
            "language_probability": self.language_probability,
            "elapsed_time": self.elapsed_time,
            "full_text": self.full_text,
            "polished_text": self.polished_text,
            "llm_model_used": self.llm_model_used,
            "llm_instructions_name": self.llm_instructions_name,
            "raw_segments_stale": self.raw_segments_stale,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text}
                for s in self.segments
            ],
            "exports": dict(self.exports),
        }

    @classmethod
    def from_dict(cls, data: dict) -> HistoryEntry:
        """Deserialize a HistoryEntry from a dictionary."""
        raw_segments = data.get("segments") or []
        segments: list[TranscriptSegment] = []
        for item in raw_segments:
            if isinstance(item, dict) and "text" in item:
                segments.append(
                    TranscriptSegment(
                        start=float(item.get("start", 0.0)),
                        end=float(item.get("end", 0.0)),
                        text=str(item.get("text", "")),
                    )
                )

        raw_exports = data.get("exports") or {}
        exports = {
            str(k): str(v)
            for k, v in raw_exports.items()
            if isinstance(k, str) and isinstance(v, str) and v
        }

        return cls(
            id=str(data["id"]),
            created_at=str(data.get("created_at") or ""),
            audio_path=str(data.get("audio_path") or ""),
            filename=str(data.get("filename") or "transcript"),
            audio_duration=float(data.get("audio_duration", 0.0)),
            slice_start=float(data.get("slice_start", 0.0)),
            slice_end=float(data["slice_end"]) if data.get("slice_end") is not None else None,
            model_name=str(data.get("model_name") or ""),
            language=data.get("language"),
            detected_language=str(data.get("detected_language") or ""),
            language_probability=float(data.get("language_probability", 0.0)),
            elapsed_time=float(data.get("elapsed_time", 0.0)),
            full_text=str(data.get("full_text") or ""),
            polished_text=data.get("polished_text"),
            llm_model_used=data.get("llm_model_used"),
            llm_instructions_name=data.get("llm_instructions_name"),
            raw_segments_stale=bool(data.get("raw_segments_stale", False)),
            segments=segments,
            exports=exports,
        )


class TranscriptHistoryStore:
    """Manages local JSON persistence for completed transcription records."""

    DEFAULT_MAX_ENTRIES = 100

    def __init__(
        self,
        history_dir: Path | str | None = None,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._explicit_dir = Path(history_dir).resolve() if history_dir is not None else None
        self.max_entries = max(1, max_entries)

    @property
    def history_dir(self) -> Path:
        return get_history_dir(self._explicit_dir)

    def _entry_path(self, entry_id: str) -> Path:
        safe_id = "".join(ch for ch in entry_id if ch.isalnum() or ch in ("-", "_"))
        if not safe_id:
            raise ValueError(f"Invalid history entry id: {entry_id!r}")
        return self.history_dir / f"{safe_id}.json"

    def _write_entry(self, entry: HistoryEntry) -> Path:
        target_dir = self.history_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = self._entry_path(entry.id)
        payload = json.dumps(entry.to_dict(), ensure_ascii=False, indent=2)

        fd, tmp_name = tempfile.mkstemp(prefix=".hist_", suffix=".tmp", dir=str(target_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, dest)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return dest

    def _prune_if_needed(self) -> None:
        entries = self.list_entries()
        if len(entries) <= self.max_entries:
            return
        for stale in entries[self.max_entries:]:
            self.delete_entry(stale.id)

    def save_track(
        self,
        track: AudioTrack,
        config: TranscriptionConfig | None = None,
        entry_id: str | None = None,
    ) -> HistoryEntry:
        """Persist a completed track and its transcript result to local JSON."""
        if track.result is None:
            raise ValueError("Cannot save track without a TranscriptionResult.")

        result = track.result
        resolved_id = entry_id or track.history_id or str(uuid.uuid4())
        existing = self.get_entry(resolved_id)

        exports: dict[str, str] = dict(existing.exports) if existing else {}
        for fmt, path_val in (
            ("docx", result.docx_path),
            ("pdf", result.pdf_path),
            ("md", result.md_path),
            ("txt", result.txt_path),
        ):
            if path_val is not None:
                exports[fmt] = str(path_val)

        slice_cfg = track.slice_config
        duration = track.info.duration or result.audio_duration
        created_at = (
            existing.created_at
            if existing and existing.created_at
            else datetime.datetime.now().isoformat(timespec="seconds")
        )

        entry = HistoryEntry(
            id=resolved_id,
            created_at=created_at,
            audio_path=str(track.file_path),
            filename=track.info.filename,
            audio_duration=float(duration),
            slice_start=float(slice_cfg.start_sec),
            slice_end=float(slice_cfg.end_sec) if slice_cfg.end_sec is not None else None,
            model_name=config.model_name if config else (existing.model_name if existing else ""),
            language=config.language if config else (existing.language if existing else None),
            detected_language=result.detected_language,
            language_probability=float(result.language_probability),
            elapsed_time=float(result.elapsed_time),
            full_text=result.full_text,
            polished_text=result.polished_text,
            llm_model_used=result.llm_model_used,
            llm_instructions_name=result.llm_instructions_name,
            raw_segments_stale=bool(result.raw_segments_stale),
            segments=list(result.segments),
            exports=exports,
        )
        self._write_entry(entry)
        track.history_id = entry.id
        self._prune_if_needed()
        return entry

    def update_exports(self, entry_id: str, exports: dict[str, Path | str]) -> HistoryEntry | None:
        """Merge newly exported file paths into an existing history entry."""
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        for fmt, path_val in exports.items():
            if path_val:
                entry.exports[fmt] = str(path_val)
        self._write_entry(entry)
        return entry

    def get_entry(self, entry_id: str) -> HistoryEntry | None:
        """Load a single history entry by ID, returning None if missing or unreadable."""
        try:
            path = self._entry_path(entry_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "id" not in data:
                return None
            return HistoryEntry.from_dict(data)
        except Exception:
            return None

    def list_entries(self, query: str = "", limit: int | None = None) -> list[HistoryEntry]:
        """List stored history entries sorted newest-first, optionally filtered by query."""
        target_dir = self.history_dir
        if not target_dir.is_dir():
            return []

        entries: list[tuple[str, float, HistoryEntry]] = []
        for path in target_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "id" not in data:
                    continue
                entry = HistoryEntry.from_dict(data)
                mtime = path.stat().st_mtime
                entries.append((entry.created_at, mtime, entry))
            except Exception:
                continue

        entries.sort(key=lambda item: (item[0], item[1]), reverse=True)
        result = [item[2] for item in entries]

        q = query.strip().lower()
        if q:
            filtered: list[HistoryEntry] = []
            for entry in result:
                haystack = " ".join([
                    entry.filename,
                    entry.model_name,
                    entry.detected_language,
                    entry.full_text,
                    entry.polished_text or "",
                ]).lower()
                if q in haystack:
                    filtered.append(entry)
            result = filtered

        if limit is not None and limit >= 0:
            result = result[:limit]
        return result

    def delete_entry(self, entry_id: str) -> bool:
        """Delete a single history entry from disk."""
        try:
            path = self._entry_path(entry_id)
        except ValueError:
            return False
        if not path.is_file():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def clear(self) -> int:
        """Delete all stored history entries, returning the count removed."""
        target_dir = self.history_dir
        if not target_dir.is_dir():
            return 0
        removed = 0
        for path in target_dir.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def to_audio_track(self, entry: HistoryEntry) -> AudioTrack:
        """Reconstruct a completed AudioTrack from a HistoryEntry without re-transcribing."""
        audio_path = Path(entry.audio_path) if entry.audio_path else Path(entry.filename)
        size_bytes = audio_path.stat().st_size if audio_path.is_file() else 0
        info = AudioInfo(
            path=audio_path,
            filename=entry.filename,
            duration=entry.audio_duration,
            size_bytes=size_bytes,
        )
        track = AudioTrack(audio_path, info)
        track.history_id = entry.id

        is_full = entry.slice_start <= 0.0 and (
            entry.slice_end is None or abs(entry.slice_end - entry.audio_duration) < 0.1
        )
        track.slice_config = SliceConfig(
            mode=SliceMode.FULL if is_full else SliceMode.RANGE,
            start_sec=entry.slice_start,
            end_sec=entry.slice_end if entry.slice_end is not None else entry.audio_duration,
        )

        docx_p = Path(entry.exports["docx"]) if entry.exports.get("docx") else None
        pdf_p = Path(entry.exports["pdf"]) if entry.exports.get("pdf") else None
        md_p = Path(entry.exports["md"]) if entry.exports.get("md") else None
        txt_p = Path(entry.exports["txt"]) if entry.exports.get("txt") else None

        result = TranscriptionResult(
            segments=list(entry.segments),
            full_text=entry.full_text,
            detected_language=entry.detected_language,
            language_probability=entry.language_probability,
            audio_duration=entry.audio_duration,
            elapsed_time=entry.elapsed_time,
            docx_path=docx_p if docx_p and docx_p.exists() else None,
            pdf_path=pdf_p if pdf_p and pdf_p.exists() else None,
            md_path=md_p if md_p and md_p.exists() else None,
            txt_path=txt_p if txt_p and txt_p.exists() else None,
            polished_text=entry.polished_text,
            llm_model_used=entry.llm_model_used,
            llm_instructions_name=entry.llm_instructions_name,
            raw_segments_stale=bool(entry.raw_segments_stale),
        )
        track.result = result
        track.status = TrackStatus.COMPLETED
        track.progress_percent = 100
        if result.speed_factor > 0:
            track.status_message = tr("worker.completed_speed", factor=result.speed_factor)
        else:
            track.status_message = TrackStatus.COMPLETED.value
        if result.docx_path:
            track.output_docx_path = result.docx_path
        return track
