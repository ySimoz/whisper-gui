"""Unit tests for local transcript history persistence and test-directory isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from whisper_gui.history import HistoryEntry, TranscriptHistoryStore, get_history_dir
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


def test_history_dir_isolation_under_pytest(monkeypatch, tmp_path: Path) -> None:
    # Under pytest, default history dir must never touch the user's home directory
    monkeypatch.delenv("WHISPER_GUI_HISTORY_DIR", raising=False)
    resolved = get_history_dir()
    assert str(Path.home()) not in str(resolved) or str(resolved).startswith(str(Path("/tmp"))) or "pytest" in str(resolved).lower()
    assert "whisper_gui_pytest_history" in str(resolved)

    # Explicit env var overrides default
    custom_env = tmp_path / "env_hist"
    monkeypatch.setenv("WHISPER_GUI_HISTORY_DIR", str(custom_env))
    assert get_history_dir() == custom_env.resolve()

    # Explicit argument overrides everything
    explicit = tmp_path / "arg_hist"
    assert get_history_dir(explicit) == explicit.resolve()


def _make_completed_track(tmp_path: Path, name: str, text: str, polished: str | None = None) -> AudioTrack:
    audio_file = tmp_path / name
    audio_file.write_bytes(b"audio")
    info = AudioInfo(path=audio_file, filename=name, duration=95.0, size_bytes=5)
    track = AudioTrack(audio_file, info)
    track.slice_config = SliceConfig(mode=SliceMode.RANGE, start_sec=5.0, end_sec=80.0)
    track.status = TrackStatus.COMPLETED
    track.progress_percent = 100
    track.result = TranscriptionResult(
        segments=[
            TranscriptSegment(start=0.0, end=2.5, text=text),
        ],
        full_text=text,
        detected_language="en",
        language_probability=0.99,
        audio_duration=75.0,
        elapsed_time=15.0,
        polished_text=polished,
        llm_model_used="deepseek-flash" if polished else None,
    )
    return track


def test_history_store_save_list_search_reopen_and_delete(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(history_dir=tmp_path / "hist")
    cfg = TranscriptionConfig(model_name="small", language="en")

    t1 = _make_completed_track(tmp_path, "standup.wav", "Sprint planning notes", "Clean sprint notes.")
    t1.result.created_dummy = True
    e1 = store.save_track(t1, cfg)
    e1_path = store.history_dir / f"{e1.id}.json"
    assert e1_path.is_file()
    assert t1.history_id == e1.id

    t2 = _make_completed_track(tmp_path, "interview.mp3", "Candidate answered architecture questions")
    e2 = store.save_track(t2, TranscriptionConfig(model_name="large-v3-turbo"))
    # Force deterministic ordering via distinct timestamps
    e1.created_at = "2026-11-16T10:00:00"
    e2.created_at = "2026-11-16T11:30:00"
    store._write_entry(e1)
    store._write_entry(e2)

    # Corrupt file should be skipped gracefully
    (store.history_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")

    entries = store.list_entries()
    assert [e.id for e in entries] == [e2.id, e1.id]
    assert e1.preview_text() == "Clean sprint notes."
    assert e2.preview_text() == "Candidate answered architecture questions"

    # Search by filename, transcript text, or model
    assert [e.id for e in store.list_entries(query="standup")] == [e1.id]
    assert [e.id for e in store.list_entries(query="architecture")] == [e2.id]
    assert [e.id for e in store.list_entries(query="large-v3-turbo")] == [e2.id]
    assert store.list_entries(limit=1) == [entries[0]]

    # Update exports & reopen even if original audio file was deleted
    docx_file = tmp_path / "standup_transcript.docx"
    docx_file.write_bytes(b"docx")
    updated = store.update_exports(e1.id, {"docx": docx_file})
    assert updated is not None
    assert updated.exports["docx"] == str(docx_file)

    Path(t1.file_path).unlink()
    reopened = store.to_audio_track(updated)
    assert reopened.history_id == e1.id
    assert reopened.status == TrackStatus.COMPLETED
    assert reopened.info.filename == "standup.wav"
    assert reopened.slice_config.mode == SliceMode.RANGE
    assert reopened.slice_config.start_sec == 5.0
    assert reopened.slice_config.end_sec == 80.0
    assert reopened.result is not None
    assert reopened.result.polished_text == "Clean sprint notes."
    assert reopened.result.docx_path == docx_file
    assert len(reopened.result.segments) == 1

    # Delete & clear
    assert store.delete_entry(e1.id) is True
    assert store.get_entry(e1.id) is None
    assert store.delete_entry("missing-id") is False
    assert store.clear() == 2  # remaining entry + corrupt.json
    assert store.list_entries() == []


def test_history_store_prunes_oldest_entries(tmp_path: Path) -> None:
    store = TranscriptHistoryStore(history_dir=tmp_path / "hist_prune", max_entries=2)
    cfg = TranscriptionConfig(model_name="tiny")

    ids = []
    for idx in range(3):
        t = _make_completed_track(tmp_path, f"clip_{idx}.wav", f"Transcript {idx}")
        entry = store.save_track(t, cfg)
        entry.created_at = f"2026-11-16T0{idx}:00:00"
        store._write_entry(entry)
        ids.append(entry.id)

    store._prune_if_needed()
    remaining = store.list_entries()
    assert [e.id for e in remaining] == [ids[2], ids[1]]
    assert store.get_entry(ids[0]) is None
