"""LLM client for polishing and reformatting raw speech-to-text transcripts.

Compatible with any OpenAI-compatible /chat/completions REST endpoint,
including DeepSeek (v4.1 flash, v3), OpenAI, Groq, OpenRouter, and Ollama.
Uses Python's standard library urllib for zero external dependencies.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

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

def normalize_model_name(provider: str, model_name: str) -> str:
    """Normalize user-entered model names to exact API endpoints."""
    name = (model_name or "").strip()
    if provider == "DeepSeek" or "deepseek" in name.lower():
        low = name.lower().replace("_", "-").replace(" ", "-")
        if "flash" in low:
            # Official DeepSeek API route for V4.1 Flash is 'deepseek-flash'
            return "deepseek-flash"
        if "pro" in low:
            return "deepseek-v4-pro"
        if not low or low == "deepseek":
            return "deepseek-flash"
    return name or "deepseek-flash"


PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-flash",
        "models": ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
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


def _build_request(url: str, payload: dict[str, Any], api_key: str) -> urllib.request.Request:
    """Build a urllib Request with appropriate headers for OpenAI-compatible APIs."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "WhisperGUI/1.0",
        },
    )
    return req


def test_llm_connection(config: LLMConfig, timeout: float = 12.0) -> tuple[bool, str]:
    """Test connection and API key validity against the configured LLM provider.

    Returns:
        tuple[bool, str]: (is_success, status_or_error_message)
    """
    if not config.api_key or not config.api_key.strip():
        # Some local servers like Ollama don't strictly require an API key,
        # but for cloud providers like DeepSeek or OpenAI it's mandatory.
        if config.provider != "Custom":
            return False, "API key cannot be empty. Please enter your API key."

    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    model_id = normalize_model_name(config.provider, config.model_name)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "user", "content": "Respond with the word 'OK'."}
        ],
        "max_tokens": 10,
        "temperature": 0.0,
    }

    try:
        req = _build_request(endpoint, payload, config.api_key)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            data = json.loads(body)
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
            return False, f"Not Found (404): Endpoint '{endpoint}' or model '{config.model_name}' not found."
        elif err.code == 429:
            return False, f"Rate Limit / Insufficient Balance (429): {msg}"
        return False, f"HTTP Error {err.code}: {msg}"

    except urllib.error.URLError as err:
        return False, f"Connection Failed: {err.reason}. Check internet connection or base URL."

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

    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    model_id = normalize_model_name(config.provider, config.model_name)
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ],
        "temperature": 0.3,
    }

    try:
        req = _build_request(endpoint, payload, config.api_key)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if cancel_check and cancel_check():
                raise InterruptedError("Polishing cancelled by user.")
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("LLM returned an empty response with no choices.")

            content = choices[0].get("message", {}).get("content", "").strip()

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
