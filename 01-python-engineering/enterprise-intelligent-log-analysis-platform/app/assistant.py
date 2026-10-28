"""AI root-cause assistant.

For an alert, a record, an event type or a free question it

1. gathers evidence from the logs: the event, its stack trace (first project
   frame highlighted), how often it occurs, what else went wrong around the
   same time, matching web 5xx responses and recent alerts;
2. matches the evidence against the Magento knowledge base; and
3. asks the configured AI provider to explain it — or, when no provider is
   enabled, writes a rule-based explanation from the same evidence.

Everything sent to a provider is masked (emails, URLs, IPs, tokens, secrets).
"""

import asyncio
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app.explorer import load_frame
from app.knowledge.magento import KnownIssue, match_issues
from app.models.log_model import ERROR_LEVELS, WARNING_LEVELS
from app.parsers.template_miner import mask_text
from app.services.llm_client import LLMError, availability, complete, model_name, provider_name

router = APIRouter(prefix="/assistant", tags=["assistant"])

WINDOW = timedelta(minutes=10)
MAX_TRACE_LINES = 14
_FRAME = re.compile(r"^#\d+\s+(?P<path>/\S+?)(?:\((?P<line>\d+)\))?:")

SYSTEM_PROMPT = (
    "You are a senior Adobe Commerce (Magento 2) support engineer helping an on-call developer find the root cause "
    "of a problem from log evidence. Use only the evidence provided; values such as <EMAIL>, <IP> and <NUM> are "
    "masked placeholders. Known-issue entries come from a curated knowledge base: those matching the event are usually reliable; those in nearby "
    "events are context only and must not be presented as the cause unless the evidence links them. "
    "Reply in plain text (no markdown tables or headings with #) using exactly these sections, each on its own line "
    "followed by short '- ' bullets: Summary, Likely cause, Evidence, Check next, Fix. Label anything uncertain as a "
    "hypothesis. Prefer concrete bin/magento commands and file paths that appear in the evidence. Do not invent log "
    "lines, versions, modules or paths. Stay under 260 words."
)


class ExplainRequest(BaseModel):
    alert_id: Optional[int] = None
    record_id: Optional[int] = None
    template_id: Optional[int] = None
    question: Optional[str] = Field(default=None, max_length=500)
    input_path: Optional[Path] = None

    @model_validator(mode="after")
    def one_target(self):
        if not any(value is not None for value in (self.alert_id, self.record_id, self.template_id, self.question)):
            raise ValueError("Provide alert_id, record_id, template_id or question.")
        return self


# -- evidence ---------------------------------------------------------------
FRAMEWORK_VENDORS = re.compile(r"/vendor/(magento/(framework|zend|zendframework1|magento2-base)|symfony|laminas|monolog|composer|guzzlehttp|psr|php-amqplib|colinmollenhour|webonyx)/")


def suspect_frame(raw: Optional[str]) -> Optional[str]:
    """The stack frame most likely to need attention.

    Preference: project code (app/code) > third-party modules > Magento modules >
    the first frame. Framework and library frames (Symfony, Laminas, Magento
    framework…) are skipped because they rarely hold the bug.
    """
    frames = []
    for line in (raw or "").splitlines():
        match = _FRAME.match(line.strip())
        if match:
            frames.append(f"{match.group('path')}:{match.group('line')}" if match.group("line") else match.group("path"))
    tiers = [
        lambda f: "/app/code/" in f,
        lambda f: "/vendor/" in f and "/vendor/magento/" not in f and not FRAMEWORK_VENDORS.search(f),
        lambda f: "/vendor/magento/module-" in f,
    ]
    for tier in tiers:
        for frame in frames:
            if tier(frame):
                return frame
    return frames[0] if frames else None


def _trace_excerpt(raw: Optional[str]) -> Optional[str]:
    if not raw or "\n" not in raw:
        return None
    lines = raw.splitlines()
    excerpt = lines[:MAX_TRACE_LINES]
    if len(lines) > MAX_TRACE_LINES:
        excerpt.append(f"… {len(lines) - MAX_TRACE_LINES} more lines")
    return mask_text("\n".join(excerpt))


def _iso(value) -> Optional[str]:
    return value.isoformat() if isinstance(value, pd.Timestamp) and not pd.isna(value) else None


def _neighbours(frame: pd.DataFrame, center: pd.Timestamp, exclude_template=None) -> dict:
    window = frame[(frame["time"] >= center - WINDOW) & (frame["time"] <= center + WINDOW)]
    problems = window[window["level"].isin(ERROR_LEVELS | WARNING_LEVELS)]
    if exclude_template is not None and "template_id" in problems:
        problems = problems[problems["template_id"] != exclude_template]
    key = "template" if "template" in problems else "message"
    grouped = (
        problems.assign(_k=problems[key].fillna(problems["message"]))
        .groupby("_k").agg(count=("level", "size"), level=("level", "first"), source=("source", "first"))
        .sort_values("count", ascending=False).head(8)
    )
    web = window[window.get("channel", pd.Series(index=window.index, dtype=object)) == "nginx"] if "channel" in window else window.iloc[0:0]
    return {
        "window_minutes": int(WINDOW.total_seconds() // 60),
        "other_problems": [
            {"event": mask_text(str(name)), "count": int(row["count"]), "level": row["level"], "source": row["source"]}
            for name, row in grouped.iterrows()
        ],
        "web_requests": int(len(web)),
        "web_5xx": int((web["level"] == "ERROR").sum()) if not web.empty else 0,
    }


def record_evidence(frame: pd.DataFrame, record_id) -> dict:
    row = frame.loc[record_id]
    same = frame[frame["template_id"] == row["template_id"]] if "template_id" in frame and not pd.isna(row.get("template_id")) else frame.loc[[record_id]]
    times = same["time"].dropna()
    evidence = {
        "event": {
            "level": row["level"],
            "source": row.get("source"),
            "time": _iso(row["time"]),
            "message": mask_text(str(row["message"])),
            "exception": row.get("exception") if isinstance(row.get("exception"), str) else None,
            "event_type": mask_text(str(row.get("template") or row["message"])),
            "suspect_frame": suspect_frame(row.get("raw")),
            "stack_trace_excerpt": _trace_excerpt(row.get("raw")),
        },
        "occurrences": {
            "count": int(len(same)),
            "first_seen": _iso(times.min()) if not times.empty else None,
            "last_seen": _iso(times.max()) if not times.empty else None,
            "by_source": same["source"].value_counts().to_dict(),
        },
    }
    if not pd.isna(row["time"]):
        evidence["around_the_same_time"] = _neighbours(frame, row["time"], row.get("template_id"))
    return evidence


def _latest(frame: pd.DataFrame, mask: pd.Series):
    matches = frame[mask]
    return matches.index[-1] if not matches.empty else None


def overview_evidence(frame: pd.DataFrame, alerts: List[dict], question: Optional[str]) -> dict:
    end = frame["time"].max()
    recent = frame[frame["time"] >= end - timedelta(hours=24)] if not pd.isna(end) else frame
    problems = recent[recent["level"].isin(ERROR_LEVELS)]
    key = "template" if "template" in problems else "message"
    top = problems.groupby(problems[key].fillna(problems["message"])).agg(count=("level", "size"), level=("level", "first"), exception=("exception", "first") if "exception" in problems else ("level", "first"))
    top = top.sort_values("count", ascending=False).head(10)
    hourly = problems.set_index("time").resample("h").size() if not problems.empty and problems["time"].notna().any() else pd.Series(dtype=int)
    return {
        "question": mask_text(question) if question else None,
        "period": {"from": _iso(recent["time"].min()), "to": _iso(end), "records": int(len(recent))},
        "severity": recent["level"].value_counts().to_dict(),
        "top_errors": [
            {"event": mask_text(str(name)), "count": int(row["count"]), "level": row["level"],
             "exception": row["exception"] if isinstance(row["exception"], str) and row["exception"] not in ERROR_LEVELS else None}
            for name, row in top.iterrows()
        ],
        "busiest_error_hours": [{"hour": _iso(index), "errors": int(count)} for index, count in hourly.sort_values(ascending=False).head(3).items()],
        "recent_alerts": [{k: (mask_text(str(a.get(k))) if k == "detail" else a.get(k)) for k in ("created_at", "severity", "title", "detail")} for a in alerts[:8]],
    }


def gather(request: Request, body: ExplainRequest) -> dict:
    frame, mode = load_frame(request, body.input_path)
    if frame.empty:
        raise LookupError("There are no log records to analyze yet.")
    monitor = getattr(request.app.state, "monitor", None)
    target: dict = {}
    record_id = body.record_id

    if body.alert_id is not None:
        if monitor is None:
            raise LookupError("Alerts exist only while live monitoring is running.")
        alert = next((a for a in monitor.store.list_alerts(limit=500) if a["id"] == body.alert_id), None)
        if alert is None:
            raise LookupError(f"Alert {body.alert_id} not found.")
        target = {"type": "alert", "rule": alert["rule"], "title": alert["title"], "severity": alert["severity"],
                  "created_at": alert["created_at"], "detail": mask_text(alert.get("detail") or "")}
        if alert["rule"] == "new_exception":
            record_id = _latest(frame, frame["exception"] == alert["key"])
        elif alert["rule"] in {"new_error_template", "critical_level"} and alert["key"].isdigit():
            record_id = _latest(frame, frame["template_id"] == int(alert["key"]))
        else:  # error spike: explain the most frequent error in the spike window
            created = pd.Timestamp(alert["created_at"])
            window = frame[(frame["time"] >= created - timedelta(minutes=10)) & (frame["time"] <= created) & frame["level"].isin(ERROR_LEVELS)]
            if not window.empty:
                key = window["template_id"].value_counts().index[0]
                record_id = window[window["template_id"] == key].index[-1]
    elif body.template_id is not None:
        record_id = _latest(frame, frame["template_id"] == body.template_id)
        if record_id is None:
            raise LookupError(f"No records for event type {body.template_id}.")
        target = {"type": "event_type", "template_id": body.template_id}

    if record_id is not None:
        if record_id not in frame.index:
            raise LookupError(f"Record {record_id} not found.")
        evidence = record_evidence(frame, record_id)
        target = target or {"type": "record", "record_id": int(record_id)}
        texts = [evidence["event"]["message"], evidence["event"]["exception"], evidence["event"]["event_type"]]
        nearby = [item["event"] for item in evidence.get("around_the_same_time", {}).get("other_problems", [])]
    else:
        alerts = monitor.store.list_alerts(limit=20) if monitor is not None else []
        evidence = overview_evidence(frame, alerts, body.question)
        target = target or {"type": "question"}
        texts = [item["event"] for item in evidence["top_errors"]] + [item.get("exception") for item in evidence["top_errors"]]
        nearby = []

    if body.question and record_id is not None:
        target["question"] = mask_text(body.question)
    # Issues matching the event itself explain it; issues matching only nearby
    # events are context and must not be presented as the cause.
    primary = _unique_issues(texts)
    related = [issue for issue in _unique_issues(nearby) if issue.id not in {item.id for item in primary}]
    return {"mode": mode, "target": target, "evidence": evidence, "known_issues": primary, "related_issues": related}


def _unique_issues(texts) -> List[KnownIssue]:
    seen, issues = set(), []
    for text in texts:
        for issue in match_issues(text):
            if issue.id not in seen:
                seen.add(issue.id)
                issues.append(issue)
    return issues


# -- answers ----------------------------------------------------------------
def rule_based_answer(context: dict) -> str:
    evidence, issues, related = context["evidence"], context["known_issues"], context.get("related_issues", [])
    lines: List[str] = []
    if "event" in evidence:
        event, occ = evidence["event"], evidence["occurrences"]
        primary = issues[0] if issues else None
        lines += ["Summary", f"- {event['level']} in {event['source']}: {event['message']}",
                  f"- Seen {occ['count']} time(s)" + (f" between {occ['first_seen']} and {occ['last_seen']}." if occ["first_seen"] else ".")]
        lines += ["Likely cause", f"- {primary.cause}" if primary else "- No known Magento pattern matches this event itself; use the evidence below to narrow it down (hypothesis needed)."]
        lines.append("Evidence")
        if event.get("exception"):
            lines.append(f"- Exception class: {event['exception']}")
        if event.get("suspect_frame"):
            lines.append(f"- Suspect stack frame (first project, third-party or Magento module frame): {event['suspect_frame']}")
        around = evidence.get("around_the_same_time", {})
        for item in around.get("other_problems", [])[:3]:
            lines.append(f"- Within ±{around['window_minutes']} min: {item['count']}× {item['level']} {item['event']}")
        if around.get("web_5xx"):
            lines.append(f"- Web server returned {around['web_5xx']} 5xx responses in the same window.")
        lines.append("Check next")
        lines += [f"- {step}" for step in (primary.fix if primary else ["Open the record in the explorer and read the full stack trace.", "Check whether the suspect frame's module changed recently (deployments, module updates)."])]
        commands = [command for issue in issues[:2] for command in issue.commands]  # only issues matching the event
        lines += ["Fix"] + ([f"- {command}" for command in commands[:5]] or ["- Apply the fix in the module named by the suspect frame, then clear cache: bin/magento cache:flush"])
        others = issues[1:] + related
        if others:
            lines.append("Known issues in nearby events (context, not necessarily the cause): " + ", ".join(issue.title for issue in others[:4]))
    else:
        lines += ["Summary", f"- {evidence['period']['records']} records from {evidence['period']['from']} to {evidence['period']['to']}."]
        if evidence["busiest_error_hours"]:
            busiest = evidence["busiest_error_hours"][0]
            lines.append(f"- Busiest error hour: {busiest['hour']} with {busiest['errors']} errors.")
        lines.append("Top problems")
        lines += [f"- {item['count']}× {item['level']} {item['event']}" for item in evidence["top_errors"][:6]]
        if issues:
            lines.append("Known issues and fixes")
            for issue in issues[:5]:
                lines.append(f"- {issue.title}: {issue.fix[0]}" + (f" ({issue.commands[0]})" if issue.commands else ""))
        if evidence.get("question"):
            lines.append("Enable an AI provider (INCIDENT_SUMMARY_ENABLED=true) for a direct answer to your question.")
    return "\n".join(lines)


def explain(request: Request, body: ExplainRequest) -> dict:
    context = gather(request, body)
    payload = {
        "target": context["target"],
        "evidence": context["evidence"],
        "known_issues_matching_event": [{k: v for k, v in issue.to_dict().items() if k in ("title", "cause", "fix", "commands")} for issue in context["known_issues"]],
        "known_issues_in_nearby_events": [issue.title for issue in context["related_issues"]],
    }
    response = {
        "target": context["target"],
        "evidence": context["evidence"],
        "known_issues": [issue.to_dict() for issue in context["known_issues"]],
        "related_issues": [issue.to_dict() for issue in context["related_issues"]],
        "data_mode": context["mode"],
    }
    reason = availability()
    if reason is None:
        try:
            answer = complete(SYSTEM_PROMPT, json.dumps(payload, default=str), max_tokens=900)
            return {**response, "mode": "llm", "provider": f"{provider_name()} · {model_name()}", "answer": answer.strip()}
        except LLMError as error:
            reason = str(error)
    return {**response, "mode": "rules", "provider": None, "answer": rule_based_answer(context), "llm_unavailable_reason": reason}


@router.post("/explain")
async def explain_endpoint(request: Request, body: ExplainRequest) -> dict:
    try:
        return await asyncio.to_thread(explain, request, body)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/status")
async def assistant_status() -> dict:
    reason = availability()
    return {"llm_available": reason is None, "provider": provider_name(), "model": model_name(), "reason": reason}
