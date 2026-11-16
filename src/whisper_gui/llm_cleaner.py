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

from whisper_gui.i18n import tr
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


# Prompt preset definitions (built-in polishing modes)
MEETING_NOTES_PROMPT = """# Meeting Notes Instructions

You are an expert meeting editor. Transform the provided raw transcript into clean, structured meeting notes.

## Rules to follow:
1. **Language & Accuracy**:
   - Write in the exact same language as the transcript.
   - Preserve all facts, names, dates, decisions, and numbers accurately; never invent details.
2. **Structure**:
   - **Summary**: 2-3 concise sentences capturing the meeting purpose and outcome.
   - **Key Topics**: Bullet points organized by topic with concrete takeaways.
   - **Decisions**: Clear list of agreed decisions (omit section if none were made).
   - **Next Steps**: Brief bullet list of follow-ups with owners if mentioned.
3. **Output Cleanliness**:
   - Strip filler words and verbal tics.
   - Return ONLY the structured markdown notes with no conversational preamble or sign-off.
"""

ACTION_ITEMS_PROMPT = """# Action Items Instructions

Extract a clear, actionable task list from the provided raw transcript.

## Rules to follow:
1. **Language & Fidelity**:
   - Write in the exact same language as the transcript.
   - Include only tasks, commitments, or follow-ups explicitly stated or clearly agreed upon.
2. **Format**:
   - Output a clean markdown checklist (`- [ ] ...`).
   - For each item, include **Owner** (if named), **Action**, and **Deadline / Context** (if stated).
   - Group related items under brief subheadings only when multiple distinct workstreams exist.
   - If no concrete action items appear, state so in one plain sentence and briefly list open questions.
3. **Output Cleanliness**:
   - Return ONLY the action items with no conversational preamble or sign-off.
"""

EXECUTIVE_SUMMARY_PROMPT = """# Executive Summary Instructions

Distill the provided raw transcript into a concise executive brief for busy readers.

## Rules to follow:
1. **Language & Fidelity**:
   - Write in the exact same language as the transcript.
   - Preserve figures, dates, commitments, and names accurately without speculation.
2. **Structure**:
   - **TL;DR**: One short paragraph (max 3 sentences) with the core message.
   - **Key Takeaways**: 3-5 crisp bullet points highlighting the most important facts or conclusions.
   - **Risks & Open Questions**: Brief bullets for unresolved issues or blockers (omit if none).
3. **Output Cleanliness**:
   - Eliminate all filler words and repetition.
   - Return ONLY the executive summary with no conversational preamble or sign-off.
"""

QA_PROMPT = """# Q&A Extraction Instructions

Reformat the provided raw transcript into a clean Questions & Answers document.

## Rules to follow:
1. **Language & Fidelity**:
   - Write in the exact same language as the transcript.
   - Preserve technical terms, figures, names, and nuance without introducing external claims.
2. **Structure**:
   - Group related exchanges into clear `**Q:**` and `**A:**` pairs.
   - If the transcript is a monologue or presentation, organize key topics as logical questions the speaker answered.
   - Strip filler words, false starts, and repetitions while keeping the speaker's intent intact.
3. **Output Cleanliness**:
   - Return ONLY the Q&A text with no conversational preamble or sign-off.
"""

PROMPT_PRESET_IDS: tuple[str, ...] = (
    "default",
    "meeting_notes",
    "action_items",
    "executive_summary",
    "qa",
)

PROMPT_PRESETS: dict[str, dict[str, str]] = {
    "default": {
        "label_key": "llm.preset_default",
        "prompt": DEFAULT_INSTRUCTION_PROMPT,
    },
    "meeting_notes": {
        "label_key": "llm.preset_meeting_notes",
        "prompt": MEETING_NOTES_PROMPT,
    },
    "action_items": {
        "label_key": "llm.preset_action_items",
        "prompt": ACTION_ITEMS_PROMPT,
    },
    "executive_summary": {
        "label_key": "llm.preset_executive_summary",
        "prompt": EXECUTIVE_SUMMARY_PROMPT,
    },
    "qa": {
        "label_key": "llm.preset_qa",
        "prompt": QA_PROMPT,
    },
}


def normalize_preset_id(preset_id: str | None) -> str:
    """Return a valid built-in prompt preset ID, defaulting to 'default'."""
    key = (preset_id or "default").strip().lower()
    return key if key in PROMPT_PRESETS else "default"


def get_preset_prompt(preset_id: str | None) -> str:
    """Return the markdown instruction prompt for a built-in preset ID."""
    key = normalize_preset_id(preset_id)
    return PROMPT_PRESETS[key]["prompt"].strip()


def get_preset_label(preset_id: str | None) -> str:
    """Return the localized display label for a built-in preset ID."""
    key = normalize_preset_id(preset_id)
    return tr(PROMPT_PRESETS[key]["label_key"])


class LLMPolishError(RuntimeError):
    """RuntimeError carrying a structured error category for actionable UI recovery."""

    def __init__(self, message: str, category: str = "unknown") -> None:
        super().__init__(message)
        self.category = category


def classify_llm_error(error: str | Exception) -> str:
    """Classify an LLM error exception or message into a recovery category."""
    if isinstance(error, LLMPolishError) and error.category:
        return error.category
    msg = str(error or "").lower()
    if any(tok in msg for tok in ("401", "403", "authentication", "invalid api key", "unauthorized")):
        return "auth"
    if any(tok in msg for tok in ("402", "429", "quota", "rate limit", "insufficient")):
        return "quota"
    if any(tok in msg for tok in ("404", "not found")):
        return "not_found"
    if any(tok in msg for tok in ("timed out", "timeout")):
        return "timeout"
    if any(
        tok in msg
        for tok in (
            "ssl",
            "certificate",
            "network error",
            "connection",
            "urlopen",
            "name or service not known",
            "nodename",
            "dns",
        )
    ):
        return "network"
    if any(tok in msg for tok in ("empty response", "empty text", "no choices", "no content blocks")):
        return "empty"
    if "http" in msg:
        return "http"
    return "unknown"


def get_llm_error_hint(error: str | Exception) -> tuple[str, str]:
    """Return (category, localized_recovery_hint) for an LLM polishing error."""
    category = classify_llm_error(error)
    hint_keys = {
        "auth": "llm.hint_auth",
        "quota": "llm.hint_quota",
        "not_found": "llm.hint_not_found",
        "timeout": "llm.hint_timeout",
        "network": "llm.hint_network",
        "empty": "llm.hint_empty",
        "http": "llm.hint_http",
        "unknown": "llm.hint_unknown",
    }
    return category, tr(hint_keys.get(category, "llm.hint_unknown"))


def load_instructions(config: LLMConfig) -> tuple[str, str]:
    """Load instruction prompt and identify its source name.

    Returns:
        tuple[str, str]: (instruction_content, source_name_description)
    """
    if config.custom_instructions_text and config.custom_instructions_text.strip():
        source = (
            tr("llm.source_file", name=config.instruction_file.name)
            if config.instruction_file
            else tr("llm.source_custom")
        )
        return config.custom_instructions_text.strip(), source

    if config.instruction_file and Path(config.instruction_file).is_file():
        try:
            content = Path(config.instruction_file).read_text(encoding="utf-8")
            return content.strip(), tr("llm.source_file", name=Path(config.instruction_file).name)
        except Exception as e:
            logger.warning(
                "Failed to read custom instruction file %s: %s. Falling back to preset.",
                config.instruction_file,
                e,
            )

    preset_id = normalize_preset_id(getattr(config, "prompt_preset", "default"))
    if preset_id == "default":
        return DEFAULT_INSTRUCTION_PROMPT.strip(), tr("llm.source_default")
    return get_preset_prompt(preset_id), tr("llm.source_preset", name=get_preset_label(preset_id))


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
            return False, tr("llm.conn_empty_key")

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
                    return True, tr("llm.conn_success", model=model_id)
                return True, tr("llm.conn_verified", status=status)
            else:
                choices = data.get("choices", [])
                if choices:
                    return True, tr("llm.conn_success", model=model_id)
                return True, tr("llm.conn_verified", status=status)

    except urllib.error.HTTPError as err:
        err_body = ""
        try:
            err_body = err.read().decode("utf-8")
            parsed = json.loads(err_body)
            msg = parsed.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body or err.reason

        if err.code == 401:
            return False, tr("llm.conn_auth_failed", msg=msg)
        elif err.code == 404:
            return False, tr("llm.conn_not_found", endpoint=endpoint, model=model_id)
        elif err.code in (402, 429):
            return False, tr("llm.conn_quota", code=err.code, msg=msg)
        return False, tr("llm.conn_http_error", code=err.code, msg=msg)

    except urllib.error.URLError as err:
        reason_str = str(err.reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason_str:
            return False, tr("llm.conn_ssl_error", reason=reason_str)
        return False, tr("llm.conn_failed", reason=reason_str)

    except TimeoutError:
        return False, tr("llm.conn_timeout", seconds=int(timeout))

    except Exception as err:
        return False, tr("llm.conn_unexpected", error=err)


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
        raise InterruptedError(tr("llm.err_cancelled"))

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
                raise InterruptedError(tr("llm.err_cancelled"))
            body = resp.read().decode("utf-8")
            data = json.loads(body)

            if is_anthropic:
                content_blocks = data.get("content", [])
                if not content_blocks:
                    raise LLMPolishError(tr("llm.err_anthropic_empty"), category="empty")
                text_parts = [
                    b.get("text", "")
                    for b in content_blocks
                    if b.get("type") == "text" or "text" in b
                ]
                content = "\n".join(text_parts).strip()
            else:
                choices = data.get("choices", [])
                if not choices:
                    raise LLMPolishError(tr("llm.err_empty_choices"), category="empty")

                msg_obj = choices[0].get("message", {})
                content = (msg_obj.get("content") or msg_obj.get("reasoning_content") or "").strip()

            if not content:
                raise LLMPolishError(tr("llm.err_empty_message"), category="empty")

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
        detail = err_msg or str(err.reason)
        if err.code in (401, 403):
            raise LLMPolishError(
                tr("llm.err_auth", code=err.code, msg=detail), category="auth"
            ) from err
        if err.code in (402, 429):
            raise LLMPolishError(
                tr("llm.err_quota", code=err.code, msg=detail), category="quota"
            ) from err
        if err.code == 404:
            raise LLMPolishError(
                tr("llm.err_not_found", endpoint=endpoint, model=model_id), category="not_found"
            ) from err
        raise LLMPolishError(
            tr("llm.err_http", code=err.code, msg=detail), category="http"
        ) from err

    except TimeoutError as err:
        raise LLMPolishError(
            tr("llm.err_timeout", seconds=int(timeout)), category="timeout"
        ) from err

    except urllib.error.URLError as err:
        reason_str = str(err.reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason_str:
            raise LLMPolishError(
                tr("llm.conn_ssl_error", reason=reason_str), category="network"
            ) from err
        if "timed out" in reason_str.lower():
            raise LLMPolishError(
                tr("llm.err_timeout", seconds=int(timeout)), category="timeout"
            ) from err
        raise LLMPolishError(
            tr("llm.err_network", reason=reason_str), category="network"
        ) from err

    except Exception as err:
        if isinstance(err, (InterruptedError, RuntimeError)):
            raise
        raise LLMPolishError(
            tr("llm.err_failed", error=err), category="unknown"
        ) from err
