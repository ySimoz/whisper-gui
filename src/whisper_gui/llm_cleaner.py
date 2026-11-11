"""LLM client for polishing and reformatting raw speech-to-text transcripts.

Supports Anthropic (Claude 3.7 Sonnet, Claude 3.5 Sonnet/Haiku, Opus) and
OpenAI-compatible REST endpoints, including DeepSeek, OpenAI, Groq, and Ollama.
Uses Python's standard library urllib for zero external dependencies.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

try:
    import certifi
except ImportError:
    certifi = None

from whisper_gui.models import LLMConfig

logger = logging.getLogger(__name__)

DEFAULT_INSTRUCTION_PROMPT = """# Speech & Transcript Polishing Instructions

You are an expert editor and speech-to-text post-processing specialist.
Your mission is to transform the provided raw audio transcript into clear, fluent, and well-structured written text.

## Rules to follow:
1. **Remove Disfluencies & Filler Words**:
   - Strip filler words and verbal tics across languages (e.g., "ehm", "uh", "um", "ah", "you know", "like", "sort of", "allora", "cioè", "tipo", "insomma", "praticamente", "diciamo").
   - Eliminate false starts, stuttered syllables, and unintentional repetitions (e.g., "we we need to" -> "we need to").
2. **Grammar, Punctuation & Sentence Flow**:
   - Fix spoken grammatical slips, run-on sentences, and incomplete phrases into coherent, grammatically sound prose.
   - Punctuate accurately with commas, periods, colons, and question marks.
3. **Preserve Meaning, Voice & Facts**:
   - Do NOT alter the speaker's core message, facts, technical terms, names, dates, or numbers.
   - Do NOT introduce ideas or commentary not present in the original transcript.
4. **Paragraph Structure**:
   - Organize the text into logical, comfortable paragraphs reflecting thematic shifts.
5. **Output Cleanliness**:
   - Return ONLY the polished transcript text.
   - Do NOT include conversational prefixes (e.g. "Here is the cleaned text:") or sign-offs.
"""


def get_ssl_context() -> ssl.SSLContext:
    """Create a resilient SSL context using certifi CA bundle if available."""
    if certifi is not None:
        try:
            cafile = certifi.where()
            if cafile and Path(cafile).is_file():
                return ssl.create_default_context(cafile=cafile)
        except Exception as e:
            logger.debug("certifi cafile error: %s", e)

    try:
        return ssl.create_default_context()
    except Exception as e:
        logger.warning("Failed to create default SSL context, using unverified fallback: %s", e)
        return ssl._create_unverified_context()


def is_anthropic_provider(provider: str = "", base_url: str = "") -> bool:
    """Check if the configured provider or base URL points to Anthropic."""
    p = (provider or "").lower()
    u = (base_url or "").lower()
    return "anthropic" in p or "claude" in p or "anthropic.com" in u


def clean_chat_endpoint(base_url: str, provider: str = "") -> str:
    """Clean and build the API endpoint URL from a base URL."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        if is_anthropic_provider(provider):
            return "https://api.anthropic.com/v1/messages"
        return "https://api.deepseek.com/v1/chat/completions"

    if is_anthropic_provider(provider, url):
        if url.endswith("/messages"):
            return url
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return f"{url}/messages"

    if url.endswith("/chat/completions"):
        return url
    return f"{url}/chat/completions"


def normalize_model_name(provider: str, model_name: str) -> str:
    """Normalize user-entered model names to exact API endpoints."""
    raw = (model_name or "").strip().strip("\"' ")
    low = raw.lower().replace("_", "-").replace(" ", "-")

    if provider == "DeepSeek" or "deepseek" in low:
        # Check for Pro models first: "DeepSeek V4 Pro", "deepseek-v4-pro", "pro", "v4-pro"
        if "pro" in low:
            return "deepseek-v4-pro"
        # Check for Flash models: "DeepSeek V4.1 Flash", "DeepSeek V4 Flash", "deepseek-flash", "flash"
        if "flash" in low or "v4.1" in low or "v4-1" in low or "chat" in low:
            return "deepseek-flash"
        if not low or low == "deepseek" or low == "default":
            return "deepseek-flash"
        return raw

    if is_anthropic_provider(provider, ""):
        # Exact matching if already valid
        if raw in (
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
            "claude-3-7-sonnet-latest",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        ):
            return raw

        if "3-7-sonnet" in low or "3.7-sonnet" in low or "3-7" in low or "3.7" in low:
            return "claude-3-7-sonnet-20250219"
        if "3-5-sonnet" in low or "3.5-sonnet" in low or ("sonnet" in low and "3-7" not in low and "3.7" not in low):
            return "claude-3-5-sonnet-20241022"
        if "3-5-haiku" in low or "3.5-haiku" in low:
            return "claude-3-5-haiku-20241022"
        if "opus" in low:
            return "claude-3-opus-20240229"
        if "haiku" in low:
            return "claude-3-haiku-20240307"
        if not low or low in ("claude", "anthropic", "default"):
            return "claude-3-7-sonnet-20250219"
        return raw

    return raw or "deepseek-flash"


PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "DeepSeek V4.1 Flash",
        "models": [
            "DeepSeek V4.1 Flash",
            "DeepSeek V4 Pro",
            "deepseek-flash",
            "deepseek-v4-pro",
        ],
    },
    "Anthropic (Claude)": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-3-7-sonnet-20250219",
        "models": [
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-haiku-20240307",
        ],
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    },
    "Custom": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3",
        "models": [],
    },
}

# Provider aliases
PROVIDER_PRESETS["Claude"] = PROVIDER_PRESETS["Anthropic (Claude)"]
PROVIDER_PRESETS["Anthropic"] = PROVIDER_PRESETS["Anthropic (Claude)"]


def load_instructions(config: LLMConfig) -> tuple[str, str]:
    """Load instruction prompt and identify its source name.

    Returns:
        tuple[str, str]: (instruction_content, source_name_description)
    """
    if config.custom_instructions_text and config.custom_instructions_text.strip():
        source = (
            f"File: {config.instruction_file.name}"
            if config.instruction_file
            else "Custom Instructions"
        )
        return config.custom_instructions_text.strip(), source

    if config.instruction_file and Path(config.instruction_file).is_file():
        try:
            content = Path(config.instruction_file).read_text(encoding="utf-8")
            return content.strip(), f"File: {Path(config.instruction_file).name}"
        except Exception as e:
            logger.warning(
                "Failed to read custom instruction file %s: %s. Falling back to default.",
                config.instruction_file,
                e,
            )

    return DEFAULT_INSTRUCTION_PROMPT.strip(), "Default Instructions"


def _build_request(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    provider: str = "",
) -> urllib.request.Request:
    """Build a urllib Request with appropriate headers for OpenAI or Anthropic APIs."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "WhisperGUI/1.0",
    }
    if is_anthropic_provider(provider, url):
        headers["x-api-key"] = api_key.strip()
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    return urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers=headers,
    )


def test_llm_connection(config: LLMConfig, timeout: float = 12.0) -> tuple[bool, str]:
    """Test connection and API key validity against the configured LLM provider.

    Returns:
        tuple[bool, str]: (is_success, status_or_error_message)
    """
    if not config.api_key or not config.api_key.strip():
        # Some local servers like Ollama don't strictly require an API key,
        # but for cloud providers like DeepSeek, Anthropic, or OpenAI it's mandatory.
        if config.provider != "Custom":
            return False, "API key cannot be empty. Please enter your API key."

    is_anthropic = is_anthropic_provider(config.provider, config.base_url)
    endpoint = clean_chat_endpoint(config.base_url, config.provider)
    model_id = normalize_model_name(config.provider, config.model_name)

    if is_anthropic:
        payload = {
            "model": model_id,
            "max_tokens": 50,
            "messages": [
                {"role": "user", "content": "Respond with the word 'OK'."}
            ],
            "temperature": 0.3,
        }
    else:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "user", "content": "Respond with the word 'OK'."}
            ],
            "max_tokens": 60,
            "temperature": 0.3,
        }

    try:
        req = _build_request(endpoint, payload, config.api_key, config.provider)
        ssl_ctx = get_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            data = json.loads(body)

            if is_anthropic:
                content_blocks = data.get("content", [])
                if content_blocks:
                    return True, f"Connection successful: {model_id} is ready."
                return True, f"Connection verified (HTTP {status})."
            else:
                choices = data.get("choices", [])
                if choices:
                    return True, f"Connection successful: {model_id} is ready."
                return True, f"Connection verified (HTTP {status})."

    except urllib.error.HTTPError as err:
        err_body = ""
        try:
            err_body = err.read().decode("utf-8")
            parsed = json.loads(err_body)
            msg = parsed.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body or err.reason

        if err.code == 401:
            return False, f"Authentication Failed (401): Invalid API Key. Details: {msg}"
        elif err.code == 404:
            return False, f"Not Found (404): Endpoint '{endpoint}' or model '{model_id}' not found."
        elif err.code in (402, 429):
            return False, f"Quota / Rate Limit Exceeded ({err.code}): {msg}"
        return False, f"HTTP Error {err.code}: {msg}"

    except urllib.error.URLError as err:
        reason_str = str(err.reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason_str:
            return False, f"SSL Certificate Error: {reason_str}. Ensure system certificates or certifi are present."
        return False, f"Connection Failed: {reason_str}. Check internet connection or base URL."

    except TimeoutError:
        return False, f"Request timed out after {int(timeout)}s. Check network or server status."

    except Exception as err:
        return False, f"Unexpected error: {err}"


test_llm_connection.__test__ = False


def polish_transcript(
    raw_text: str,
    config: LLMConfig,
    instructions: str | None = None,
    cancel_check: Callable[[], bool] | None = None,
    timeout: float = 180.0,
) -> str:
    """Send raw transcript to LLM for reformatting and polishing.

    Args:
        raw_text: The complete raw transcript text from Whisper.
        config: LLMConfig containing API key, model name, and base URL.
        instructions: Optional explicit instructions text. If None, loads from config.
        cancel_check: Optional callback returning True if user cancelled operation.
        timeout: Network timeout in seconds.

    Returns:
        str: Polished and reformatted transcript text.

    Raises:
        RuntimeError: If connection fails or returns an error response.
        InterruptedError: If operation was cancelled by user.
    """
    if not raw_text or not raw_text.strip():
        return ""

    if cancel_check and cancel_check():
        raise InterruptedError("Polishing cancelled by user.")

    system_prompt = instructions
    if system_prompt is None:
        system_prompt, _ = load_instructions(config)

    is_anthropic = is_anthropic_provider(config.provider, config.base_url)
    endpoint = clean_chat_endpoint(config.base_url, config.provider)
    model_id = normalize_model_name(config.provider, config.model_name)

    if is_anthropic:
        payload = {
            "model": model_id,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": raw_text},
            ],
            "temperature": 0.3,
        }
    else:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_text},
            ],
            "temperature": 0.3,
        }

    try:
        req = _build_request(endpoint, payload, config.api_key, config.provider)
        ssl_ctx = get_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            if cancel_check and cancel_check():
                raise InterruptedError("Polishing cancelled by user.")
            body = resp.read().decode("utf-8")
            data = json.loads(body)

            if is_anthropic:
                content_blocks = data.get("content", [])
                if not content_blocks:
                    raise RuntimeError("Anthropic returned an empty response with no content blocks.")
                text_parts = [
                    b.get("text", "")
                    for b in content_blocks
                    if b.get("type") == "text" or "text" in b
                ]
                content = "\n".join(text_parts).strip()
            else:
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError("LLM returned an empty response with no choices.")

                msg_obj = choices[0].get("message", {})
                content = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()

            if not content:
                raise RuntimeError("LLM returned an empty text message.")

            # If the LLM wrapped the entire response in markdown code blocks, unwrap it
            if content.startswith("```markdown\n") and content.endswith("```"):
                content = content[len("```markdown\n") : -3].strip()
            elif content.startswith("```\n") and content.endswith("```"):
                content = content[4:-3].strip()

            return content

    except urllib.error.HTTPError as err:
        err_msg = ""
        try:
            err_msg = json.loads(err.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        raise RuntimeError(f"LLM API Error ({err.code}): {err_msg or err.reason}") from err

    except urllib.error.URLError as err:
        raise RuntimeError(f"Network error communicating with LLM API: {err.reason}") from err

    except Exception as err:
        if isinstance(err, (InterruptedError, RuntimeError)):
            raise
        raise RuntimeError(f"Failed to polish transcript: {err}") from err
