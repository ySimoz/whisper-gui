"""Unit tests for transcriber memory caching, disk detection, and unloading."""

from unittest.mock import MagicMock

import pytest

from whisper_gui.audio_utils import CancelledError
from whisper_gui.transcriber import (
    Transcriber,
    delete_cached_model,
    download_model_with_progress,
    estimate_model_ram_mb,
    get_model_cache_dir,
    get_model_cache_size_mb,
    is_model_downloaded_on_disk,
)


def test_estimate_model_ram_mb():
    assert estimate_model_ram_mb("large-v3-turbo") == 1500
    assert estimate_model_ram_mb("tiny") == 75
    assert estimate_model_ram_mb("unknown-model") == 1000


def test_is_model_downloaded_on_disk(tmp_path, monkeypatch):
    assert is_model_downloaded_on_disk("nonexistent-model-xyz") is False
    assert isinstance(is_model_downloaded_on_disk("large-v3-turbo"), bool)

    # Deterministically verify positive detection using a mock cache structure
    fake_cache = tmp_path / "hf_cache"
    fake_snapshot = fake_cache / "models--Systran--faster-whisper-tiny" / "snapshots" / "main"
    fake_snapshot.mkdir(parents=True)
    (fake_snapshot / "model.bin").touch()

    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(fake_cache))
    assert is_model_downloaded_on_disk("tiny") is True


def test_transcriber_load_and_unload_lifecycle():
    transcriber = Transcriber()
    assert transcriber.is_loaded is False
    assert transcriber.loaded_model_name is None

    # Load tiny model for testing
    model = transcriber.get_or_load_model("tiny", device="cpu", compute_type="int8", cpu_threads=2)
    assert model is not None
    assert transcriber.is_loaded is True
    assert transcriber.loaded_model_name == "tiny"

    # Explicit unload
    transcriber.unload_model()
    assert transcriber.is_loaded is False
    assert transcriber.loaded_model_name is None


def test_model_cache_dir_size_and_delete(tmp_path, monkeypatch):
    fake_cache = tmp_path / "hf_cache"
    fake_cache.mkdir()
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(fake_cache))

    assert get_model_cache_dir("") is None
    cache_dir = get_model_cache_dir("tiny")
    assert cache_dir == fake_cache / "models--Systran--faster-whisper-tiny"
    assert get_model_cache_size_mb("tiny") == 0.0
    assert delete_cached_model("tiny") is False

    blobs_dir = cache_dir / "blobs"
    snap_dir = cache_dir / "snapshots" / "main"
    blobs_dir.mkdir(parents=True)
    snap_dir.mkdir(parents=True)

    blob_file = blobs_dir / "abc123"
    blob_file.write_bytes(b"x" * (1024 * 1024))
    snap_link = snap_dir / "model.bin"
    snap_link.symlink_to(blob_file)

    assert is_model_downloaded_on_disk("tiny") is True
    assert get_model_cache_size_mb("tiny") == 1.0

    assert delete_cached_model("tiny") is True
    assert not cache_dir.exists()
    assert is_model_downloaded_on_disk("tiny") is False
    assert get_model_cache_size_mb("tiny") == 0.0


def test_download_model_with_progress_and_cancel(tmp_path, monkeypatch):
    fake_cache = tmp_path / "hf_cache"
    fake_cache.mkdir()
    monkeypatch.setattr("huggingface_hub.constants.HF_HUB_CACHE", str(fake_cache))

    snap_out = tmp_path / "snapshot_dir"
    snap_out.mkdir()

    def fake_snapshot_download(repo_id, **kwargs):
        assert repo_id == "Systran/faster-whisper-small"
        tqdm_cls = kwargs.get("tqdm_class")
        assert tqdm_cls is not None
        bar = tqdm_cls(
            name="huggingface_hub.snapshot_download.transfer",
            desc="Downloading bytes",
            total=10 * 1024 * 1024,
            initial=0,
            unit="B",
        )
        bar.update(5 * 1024 * 1024)
        bar.update(5 * 1024 * 1024)
        bar.close()
        return str(snap_out)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_download)

    progress_events: list[tuple[int, str]] = []
    status_events: list[str] = []
    result = download_model_with_progress(
        "small",
        on_progress=lambda pct, msg: progress_events.append((pct, msg)),
        on_status=lambda msg: status_events.append(msg),
    )
    assert result == str(snap_out)
    assert progress_events[0][0] == -1
    assert any(pct == 100 and "10.0 / 10.0 MB" in msg for pct, msg in progress_events)
    assert any("Downloading 'small'" in s for s in status_events)

    # Test cancellation mid-download
    stop_flag = {"stop": False}

    def fake_snapshot_cancel(repo_id, **kwargs):
        tqdm_cls = kwargs["tqdm_class"]
        bar = tqdm_cls(
            name="huggingface_hub.snapshot_download.transfer",
            desc="Downloading bytes",
            total=1024,
            initial=0,
            unit="B",
        )
        stop_flag["stop"] = True
        bar.update(256)
        return str(snap_out)

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_snapshot_cancel)
    with pytest.raises(CancelledError):
        download_model_with_progress("small", should_stop=lambda: stop_flag["stop"])


def test_transcriber_get_or_load_model_reports_progress(tmp_path, monkeypatch):
    fake_model_dir = tmp_path / "model_dir"
    fake_model_dir.mkdir()

    monkeypatch.setattr("whisper_gui.transcriber.is_model_downloaded_on_disk", lambda _m: False)
    monkeypatch.setattr(
        "whisper_gui.transcriber.download_model_with_progress",
        lambda model_name, on_progress=None, on_status=None, should_stop=None, local_files_only=False: (
            on_progress(50, "5.0 / 10.0 MB (50%)") if on_progress else None,
            str(fake_model_dir),
        )[1],
    )
    fake_whisper_cls = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("whisper_gui.transcriber.WhisperModel", fake_whisper_cls)

    progress_events: list[tuple[int, str]] = []
    status_events: list[str] = []
    t = Transcriber()
    t.get_or_load_model(
        "small",
        on_status=lambda msg: status_events.append(msg),
        on_progress=lambda pct, msg: progress_events.append((pct, msg)),
    )

    assert (50, "5.0 / 10.0 MB (50%)") in progress_events
    assert any(pct == -1 for pct, _ in progress_events)
    assert progress_events[-1][0] == 0
    assert any("Loading 'small'" in s for s in status_events)
    fake_whisper_cls.assert_called_once_with(
        str(fake_model_dir), device="cpu", compute_type="int8", cpu_threads=6
    )
