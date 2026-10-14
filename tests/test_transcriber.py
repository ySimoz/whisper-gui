"""Unit tests for transcriber memory caching, disk detection, and unloading."""

from whisper_gui.transcriber import (
    Transcriber,
    estimate_model_ram_mb,
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
