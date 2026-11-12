"""Unit tests for transcriber memory caching, disk detection, and unloading."""

from whisper_gui.transcriber import (
    Transcriber,
    delete_cached_model,
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
