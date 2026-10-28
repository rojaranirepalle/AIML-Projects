"""Opt-in incident summarization through OpenAI, Anthropic, or Gemini APIs."""

import json

from app.parsers.template_miner import mask_text
from app.services.llm_client import LLMError, complete

SYSTEM_PROMPT = (
    "Summarize the supplied operational log analytics for an on-call engineer. "
    "Event templates group lines that differ only in variable values such as IDs and IPs. "
    "Separate observed facts from hypotheses, mention likely impact and next checks, "
    "and do not claim a root cause unless the evidence supports it."
)


class SummarizationError(RuntimeError):
    pass


def summarize_incident(summary: dict) -> str:
    # Only aggregates, templates and masked messages are sent; raw lines can
    # contain customer emails, URLs and tokens.
    def masked(items: list) -> list:
        return [{**item, "message": mask_text(str(item.get("message", "")))} for item in items]

    access = summary.get("access") or {}
    prompt_data = {
        "total_logs": summary.get("total_logs"),
        "severity_distribution": summary.get("severity_distribution"),
        "error_rate": summary.get("error_rate"),
        "event_template_count": summary.get("template_count"),
        "top_event_templates": summary.get("top_templates", []),
        "rare_event_templates": summary.get("ml_anomalies", {}).get("anomalous_templates", [])[:10],
        "top_exceptions": summary.get("top_exceptions", {}),
        "known_issues": [{k: issue[k] for k in ("title", "count", "severity", "cause")} for issue in summary.get("known_issues", [])],
        "web_traffic": {k: access.get(k) for k in ("requests", "status_classes", "error_rate_5xx", "latency", "top_5xx_routes")} if access.get("available") else None,
        "high_severity_anomalies": masked(summary.get("anomalies", [])[:20]),
        "ml_anomalies": masked(summary.get("ml_anomalies", {}).get("anomalies", [])[:20]),
        "forecast": summary.get("forecast"),
    }
    try:
        return complete(SYSTEM_PROMPT, json.dumps(prompt_data, default=str))
    except LLMError as error:
        raise SummarizationError(str(error)) from error
