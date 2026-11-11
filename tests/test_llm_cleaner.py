"""Unit tests for the LLM cleaner module (DeepSeek V4.1 Flash, OpenAI, Groq)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

from whisper_gui.llm_cleaner import (
    DEFAULT_INSTRUCTION_PROMPT,
    PROVIDER_PRESETS,
    _build_request,
    clean_chat_endpoint,
    get_ssl_context,
    is_anthropic_provider,
    load_instructions,
    normalize_model_name,
    polish_transcript,
    test_llm_connection as _check_conn,
)
from whisper_gui.models import LLMConfig


def test_provider_presets():
    assert "DeepSeek" in PROVIDER_PRESETS
    ds = PROVIDER_PRESETS["DeepSeek"]
    assert ds["default_model"] == "DeepSeek V4.1 Flash"
    assert "DeepSeek V4.1 Flash" in ds["models"]
    assert "DeepSeek V4 Pro" in ds["models"]
    assert "deepseek-flash" in ds["models"]
    assert "deepseek-v4-pro" in ds["models"]
    assert "deepseek.com" in ds["base_url"]

    # Anthropic / Claude preset
    assert "Anthropic (Claude)" in PROVIDER_PRESETS
    claude = PROVIDER_PRESETS["Anthropic (Claude)"]
    assert claude["default_model"] == "claude-3-7-sonnet-20250219"
    assert "claude-3-7-sonnet-20250219" in claude["models"]
    assert "claude-3-5-sonnet-20241022" in claude["models"]
    assert "claude-3-5-haiku-20241022" in claude["models"]
    assert "claude-3-opus-20240229" in claude["models"]
    assert "claude-3-haiku-20240307" in claude["models"]
    assert "api.anthropic.com" in claude["base_url"]

    # Aliases
    assert PROVIDER_PRESETS["Claude"] == claude
    assert PROVIDER_PRESETS["Anthropic"] == claude


def test_clean_chat_endpoint():
    assert clean_chat_endpoint("https://api.deepseek.com") == "https://api.deepseek.com/chat/completions"
    assert clean_chat_endpoint("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1/chat/completions"
    assert clean_chat_endpoint("https://api.deepseek.com/v1/") == "https://api.deepseek.com/v1/chat/completions"
    assert clean_chat_endpoint("https://api.deepseek.com/v1/chat/completions") == "https://api.deepseek.com/v1/chat/completions"
    assert clean_chat_endpoint("") == "https://api.deepseek.com/v1/chat/completions"

    # Anthropic endpoint resolution
    assert clean_chat_endpoint("", "Anthropic (Claude)") == "https://api.anthropic.com/v1/messages"
    assert clean_chat_endpoint("https://api.anthropic.com", "Anthropic (Claude)") == "https://api.anthropic.com/v1/messages"
    assert clean_chat_endpoint("https://api.anthropic.com/v1", "Anthropic (Claude)") == "https://api.anthropic.com/v1/messages"
    assert clean_chat_endpoint("https://api.anthropic.com/v1/messages", "Anthropic (Claude)") == "https://api.anthropic.com/v1/messages"
    assert clean_chat_endpoint("https://api.anthropic.com/v1") == "https://api.anthropic.com/v1/messages"


def test_normalize_model_name():
    # Flash variants
    assert normalize_model_name("DeepSeek", "DeepSeek V4.1 Flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "DeepSeek V4 Flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "deepseek-v4.1-flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "deepseekv4.1 flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "deepseek-flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "flash") == "deepseek-flash"
    assert normalize_model_name("DeepSeek", "deepseek-chat") == "deepseek-flash"

    # Pro variants
    assert normalize_model_name("DeepSeek", "DeepSeek V4 Pro") == "deepseek-v4-pro"
    assert normalize_model_name("DeepSeek", "deepseek-v4-pro") == "deepseek-v4-pro"
    assert normalize_model_name("DeepSeek", "v4-pro") == "deepseek-v4-pro"
    assert normalize_model_name("DeepSeek", "pro") == "deepseek-v4-pro"

    # Anthropic / Claude variants
    assert normalize_model_name("Anthropic (Claude)", "claude-3-7-sonnet-20250219") == "claude-3-7-sonnet-20250219"
    assert normalize_model_name("Anthropic (Claude)", "Claude 3.7 Sonnet") == "claude-3-7-sonnet-20250219"
    assert normalize_model_name("Anthropic (Claude)", "claude-3.7-sonnet") == "claude-3-7-sonnet-20250219"
    assert normalize_model_name("Anthropic (Claude)", "sonnet-3.7") == "claude-3-7-sonnet-20250219"
    assert normalize_model_name("Anthropic (Claude)", "Claude 3.5 Sonnet") == "claude-3-5-sonnet-20241022"
    assert normalize_model_name("Anthropic (Claude)", "sonnet") == "claude-3-5-sonnet-20241022"
    assert normalize_model_name("Anthropic (Claude)", "Claude 3.5 Haiku") == "claude-3-5-haiku-20241022"
    assert normalize_model_name("Anthropic (Claude)", "Claude 3 Opus") == "claude-3-opus-20240229"
    assert normalize_model_name("Anthropic (Claude)", "opus") == "claude-3-opus-20240229"
    assert normalize_model_name("Anthropic (Claude)", "haiku") == "claude-3-haiku-20240307"
    assert normalize_model_name("Anthropic (Claude)", "") == "claude-3-7-sonnet-20250219"

    # Other providers
    assert normalize_model_name("OpenAI", "gpt-4o") == "gpt-4o"
    assert normalize_model_name("Groq", "llama-3.3-70b-versatile") == "llama-3.3-70b-versatile"


def test_load_instructions_default():
    cfg = LLMConfig(enabled=True)
    text, name = load_instructions(cfg)
    assert "Speech & Transcript Polishing Instructions" in text
    assert "Default Instructions" in name
    assert "Remove Disfluencies" in text


def test_load_instructions_custom_file(tmp_path: Path):
    custom_md = tmp_path / "custom_prompt.md"
    custom_md.write_text("# My Custom Polishing Rules\n1. Be super concise.", encoding="utf-8")

    cfg = LLMConfig(enabled=True, instruction_file=custom_md)
    text, name = load_instructions(cfg)
    assert text == "# My Custom Polishing Rules\n1. Be super concise."
    assert "custom_prompt.md" in name


def test_load_instructions_custom_text():
    cfg = LLMConfig(enabled=True, custom_instructions_text="Direct prompt string")
    text, name = load_instructions(cfg)
    assert text == "Direct prompt string"


def test_test_llm_connection_empty_key():
    cfg = LLMConfig(enabled=True, provider="DeepSeek", api_key="")
    ok, msg = _check_conn(cfg)
    assert not ok
    assert "API key cannot be empty" in msg


def test_test_llm_connection_success():
    cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4.1-flash",
        api_key="sk-testkey123",
        base_url="https://api.deepseek.com/v1",
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "OK"}}]
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        ok, msg = _check_conn(cfg)
        assert ok
        assert "deepseek-flash is ready" in msg


def test_test_llm_connection_success_pro():
    cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="DeepSeek V4 Pro",
        api_key="sk-pro-testkey",
        base_url="https://api.deepseek.com",
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "OK"}}]
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        ok, msg = _check_conn(cfg)
        assert ok
        assert "deepseek-v4-pro is ready" in msg


def test_test_llm_connection_auth_error():
    cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4.1-flash",
        api_key="sk-invalid",
        base_url="https://api.deepseek.com/v1",
    )

    fp_mock = MagicMock()
    fp_mock.read.return_value = json.dumps({
        "error": {"message": "Authentication failed"}
    }).encode("utf-8")
    http_err = urllib.error.HTTPError(
        url="https://api.deepseek.com/v1/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=fp_mock,
    )

    with patch("urllib.request.urlopen", side_effect=http_err):
        ok, msg = _check_conn(cfg)
        assert not ok
        assert "Authentication Failed (401)" in msg


def test_polish_transcript_success():
    cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4.1-flash",
        api_key="sk-valid123",
        base_url="https://api.deepseek.com/v1",
    )

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Buongiorno a tutti. Oggi esaminiamo l'intelligenza artificiale."
            }
        }]
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        raw_text = "Ehm, buongiorno a tutti, allora oggi parliamo di intelligenza artificiale."
        result = polish_transcript(raw_text, cfg)
        assert result == "Buongiorno a tutti. Oggi esaminiamo l'intelligenza artificiale."


def test_polish_transcript_unwraps_markdown():
    cfg = LLMConfig(
        enabled=True,
        provider="DeepSeek",
        model_name="deepseek-v4.1-flash",
        api_key="sk-valid123",
    )

    wrapped_content = "```markdown\nCleaned polished text without code block.\n```"
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": wrapped_content}}]
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        result = polish_transcript("raw", cfg)
        assert result == "Cleaned polished text without code block."


def test_polish_transcript_empty_text():
    cfg = LLMConfig(enabled=True)
    assert polish_transcript("", cfg) == ""
    assert polish_transcript("   ", cfg) == ""


def test_anthropic_build_request_headers():
    req = _build_request(
        url="https://api.anthropic.com/v1/messages",
        payload={"model": "claude-3-7-sonnet-20250219"},
        api_key="sk-ant-api03-testkey",
        provider="Anthropic (Claude)",
    )
    assert req.headers["X-api-key"] == "sk-ant-api03-testkey"
    assert req.headers["Anthropic-version"] == "2023-06-01"
    assert "Authorization" not in req.headers


def test_test_llm_connection_anthropic_success():
    cfg = LLMConfig(
        enabled=True,
        provider="Anthropic (Claude)",
        model_name="claude-3-7-sonnet-20250219",
        api_key="sk-ant-test123",
        base_url="https://api.anthropic.com/v1",
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = json.dumps({
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "OK"}],
        "model": "claude-3-7-sonnet-20250219",
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        ok, msg = _check_conn(cfg)
        assert ok
        assert "claude-3-7-sonnet-20250219 is ready" in msg

        # Inspect request
        called_req = mock_urlopen.call_args[0][0]
        assert called_req.full_url == "https://api.anthropic.com/v1/messages"
        assert called_req.headers["X-api-key"] == "sk-ant-test123"
        assert called_req.headers["Anthropic-version"] == "2023-06-01"


def test_polish_transcript_anthropic_success():
    cfg = LLMConfig(
        enabled=True,
        provider="Anthropic (Claude)",
        model_name="claude-3-7-sonnet-20250219",
        api_key="sk-ant-test123",
        base_url="https://api.anthropic.com/v1",
    )

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "id": "msg_456",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Polished text cleanly produced by Claude."}
        ],
        "model": "claude-3-7-sonnet-20250219",
    }).encode("utf-8")

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response
        result = polish_transcript("Raw transcription input text", cfg)
        assert result == "Polished text cleanly produced by Claude."

        called_req = mock_urlopen.call_args[0][0]
        sent_payload = json.loads(called_req.data.decode("utf-8"))
        assert sent_payload["model"] == "claude-3-7-sonnet-20250219"
        assert sent_payload["max_tokens"] == 4096
        assert "Speech & Transcript Polishing Instructions" in sent_payload["system"]
        assert sent_payload["messages"] == [
            {"role": "user", "content": "Raw transcription input text"}
        ]
