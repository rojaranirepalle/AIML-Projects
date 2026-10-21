"""Opt-in incident summarization through OpenAI, Anthropic, or Gemini APIs."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from app.config.settings import settings


SYSTEM_PROMPT = (
    "Summarize the supplied operational log analytics for an on-call engineer. "
    "Event templates group lines that differ only in variable values such as IDs and IPs. "
    "Separate observed facts from hypotheses, mention likely impact and next checks, "
    "and do not claim a root cause unless the evidence supports it."
)


class SummarizationError(RuntimeError):
    pass


def summarize_incident(summary: dict) -> str:
    if not settings.incident_summary_enabled:
        raise SummarizationError("Incident summaries are disabled. Set INCIDENT_SUMMARY_ENABLED=true to enable them.")
    provider = settings.incident_summary_provider.strip().lower()
    if provider not in {"openai", "anthropic", "gemini"}:
        raise SummarizationError("INCIDENT_SUMMARY_PROVIDER must be 'openai', 'anthropic', or 'gemini'.")
    configured_key = settings.incident_summary_api_key
    if configured_key is None or not configured_key.get_secret_value().strip():
        configured_key = {
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
            "gemini": settings.gemini_api_key,
        }[provider]
    if configured_key is None or not configured_key.get_secret_value().strip():
        variable = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
        }[provider]
        raise SummarizationError(f"Set {variable} before requesting an incident summary.")

    prompt_data = {
        "total_logs": summary.get("total_logs"),
        "severity_distribution": summary.get("severity_distribution"),
        "error_rate": summary.get("error_rate"),
        "event_template_count": summary.get("template_count"),
        "top_event_templates": summary.get("top_templates", []),
        "rare_event_templates": summary.get("ml_anomalies", {}).get("anomalous_templates", [])[:10],
        "high_severity_anomalies": summary.get("anomalies", [])[:20],
        "ml_anomalies": summary.get("ml_anomalies", {}).get("anomalies", [])[:20],
        "forecast": summary.get("forecast"),
    }
    if provider == "openai":
        endpoint = (settings.incident_summary_api_base or "https://api.openai.com/v1").rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        payload = {
            "model": settings.incident_summary_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {"role": "user", "content": json.dumps(prompt_data, default=str)},
            ],
        }
        headers = {"Authorization": f"Bearer {configured_key.get_secret_value()}"}
    elif provider == "anthropic":
        endpoint = (settings.incident_summary_api_base or "https://api.anthropic.com/v1").rstrip("/")
        if not endpoint.endswith("/messages"):
            endpoint += "/messages"
        payload = {
            "model": settings.anthropic_model,
            "max_tokens": 1200,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": json.dumps(prompt_data, default=str)}],
        }
        headers = {
            "x-api-key": configured_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
        }
    else:
        endpoint = (settings.incident_summary_api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        model = quote(settings.gemini_model, safe="-_.")
        operation = f"/models/{model}:generateContent"
        if not endpoint.endswith(operation):
            endpoint += operation
        payload = {
            "systemInstruction": {
                "parts": [
                    {"text": SYSTEM_PROMPT}
                ]
            },
            "contents": [
                {"role": "user", "parts": [{"text": json.dumps(prompt_data, default=str)}]}
            ],
        }
        headers = {"x-goog-api-key": configured_key.get_secret_value()}
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **headers,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.incident_summary_timeout_seconds) as response:
            response_body = json.loads(response.read().decode("utf-8"))
        if provider == "openai":
            return response_body["choices"][0]["message"]["content"]
        if provider == "anthropic":
            return "\n".join(
                block["text"] for block in response_body["content"] if block.get("type") == "text"
            )
        return "\n".join(
            part["text"]
            for part in response_body["candidates"][0]["content"]["parts"]
            if "text" in part
        )
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SummarizationError(f"Incident summary provider request failed: {error}") from error
