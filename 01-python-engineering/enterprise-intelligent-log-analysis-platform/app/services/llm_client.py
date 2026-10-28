"""Minimal, dependency-free client for OpenAI, Anthropic and Gemini chat APIs.

Outbound calls are opt-in (``INCIDENT_SUMMARY_ENABLED=true``) and use each
provider's native REST format. Callers are responsible for masking log text
before passing it here.
"""

import json
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config.settings import settings
from app.config.llm_settings import effective_settings

PROVIDERS = {"openai", "anthropic", "gemini"}
KEY_VARIABLES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


class LLMError(RuntimeError):
    pass


def provider_name() -> str:
    return effective_settings().incident_summary_provider.strip().lower()


def model_name() -> str:
    config = effective_settings()
    provider = config.incident_summary_provider.strip().lower()
    return {"openai": config.incident_summary_model, "anthropic": config.anthropic_model}.get(provider, config.gemini_model)


def availability() -> Optional[str]:
    """``None`` when a provider call can be made, otherwise the reason it cannot."""
    config = effective_settings()
    if not config.incident_summary_enabled:
        return "AI provider calls are disabled. Set INCIDENT_SUMMARY_ENABLED=true to enable them."
    provider = config.incident_summary_provider.strip().lower()
    if provider not in PROVIDERS:
        return "INCIDENT_SUMMARY_PROVIDER must be 'openai', 'anthropic', or 'gemini'."
    if _api_key(provider) is None:
        return f"Set {KEY_VARIABLES[provider]} before requesting AI analysis."
    return None


def _api_key(provider: str) -> Optional[str]:
    config = effective_settings()
    for candidate in ({
        "openai": config.openai_api_key, "anthropic": config.anthropic_api_key, "gemini": config.gemini_api_key,
    }[provider], config.incident_summary_api_key):
        if candidate is not None and candidate.get_secret_value().strip():
            return candidate.get_secret_value().strip()
    return None


def complete(system_prompt: str, user_content: str, max_tokens: int = 1200) -> str:
    reason = availability()
    if reason:
        raise LLMError(reason)
    config = effective_settings()
    provider = config.incident_summary_provider.strip().lower()
    key = _api_key(provider)
    if provider == "openai":
        endpoint = (settings.incident_summary_api_base or "https://api.openai.com/v1").rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = {
            "model": config.incident_summary_model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        }
        headers = {"Authorization": f"Bearer {key}"}
    elif provider == "anthropic":
        endpoint = (settings.incident_summary_api_base or "https://api.anthropic.com/v1").rstrip("/")
        if not endpoint.endswith("/messages"):
            endpoint += "/messages"
        payload = {
            "model": config.anthropic_model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        endpoint = (settings.incident_summary_api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        operation = f"/models/{quote(config.gemini_model, safe='-_.')}:generateContent"
        if not endpoint.endswith(operation):
            endpoint += operation
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_content}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
        }
        headers = {"x-goog-api-key": key}

    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                      headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=settings.incident_summary_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        if provider == "openai":
            return body["choices"][0]["message"]["content"]
        if provider == "anthropic":
            return "\n".join(block["text"] for block in body["content"] if block.get("type") == "text")
        return "\n".join(part["text"] for part in body["candidates"][0]["content"]["parts"] if "text" in part)
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LLMError(f"AI provider request failed: {error}") from error
