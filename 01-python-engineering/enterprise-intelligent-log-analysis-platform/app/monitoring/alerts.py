"""Alert rules evaluated on each batch of newly ingested (non-baseline) records.

Rules
-----
* ``critical_level``     ALERT/EMERGENCY record (Monolog's highest levels).
* ``new_exception``      an exception class never seen before in this store.
* ``new_error_template`` an error-level event type never seen before.
* ``error_spike``        errors in the last window exceed both a floor and a
                         multiple of the average window over the previous day.

Every rule has a per-key cooldown so one recurring problem raises one alert.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List

from app.models.log_model import ERROR_LEVELS
from app.monitoring.store import MonitorStore, iso

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
TOP_LEVELS = {"ALERT", "EMERGENCY"}


@dataclass
class AlertConfig:
    cooldown_minutes: int = 15
    spike_window_minutes: int = 5
    spike_baseline_hours: int = 24
    spike_min_errors: int = 10
    spike_factor: float = 3.0


def _short(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def evaluate(store: MonitorStore, rows: List[dict], templates: Dict[int, str], now: datetime, config: AlertConfig) -> List[dict]:
    """Return alerts for ``rows``; call before the rows are inserted into ``store``."""
    live = [row for row in rows if not row.get("baseline")]
    if not live:
        return []
    candidates: List[dict] = []

    for row in live:
        if row["level"] in TOP_LEVELS:
            candidates.append({
                "rule": "critical_level", "key": str(row["template_id"]), "severity": "critical",
                "title": f"{row['level']} in {row['source']}", "detail": _short(row["message"]), "source": row["source"],
            })

    known_exceptions = store.known_exceptions()
    new_exceptions: Dict[str, List[dict]] = {}
    for row in live:
        if row.get("exception") and row["exception"] not in known_exceptions:
            new_exceptions.setdefault(row["exception"], []).append(row)
    for exception, matches in new_exceptions.items():
        candidates.append({
            "rule": "new_exception", "key": exception, "severity": "high",
            "title": f"New exception: {exception.rsplit(chr(92), 1)[-1]}",
            "detail": f"{exception} — {_short(matches[0]['message'])}",
            "source": matches[0]["source"], "record_count": len(matches),
        })

    known_templates = store.known_error_templates()
    # Records already explained by a more specific alert do not also raise "new error type".
    covered = {row["template_id"] for matches in new_exceptions.values() for row in matches}
    covered |= {row["template_id"] for row in live if row["level"] in TOP_LEVELS}
    new_templates: Dict[int, List[dict]] = {}
    for row in live:
        template_id = row["template_id"]
        if row["level"] in ERROR_LEVELS and template_id not in known_templates and template_id not in covered:
            new_templates.setdefault(template_id, []).append(row)
    for template_id, matches in new_templates.items():
        candidates.append({
            "rule": "new_error_template", "key": str(template_id), "severity": "medium",
            "title": f"New error type in {matches[0]['source']}", "detail": _short(templates.get(template_id, matches[0]["message"])),
            "source": matches[0]["source"], "record_count": len(matches),
        })

    spike = _error_spike(store, live, now, config)
    if spike:
        candidates.append(spike)

    cooldown = timedelta(minutes=config.cooldown_minutes)
    alerts = []
    for alert in candidates:
        last = store.last_alert_time(alert["rule"], alert["key"])
        if last is None or now - last >= cooldown:
            alerts.append(alert)
    return alerts


def _error_spike(store: MonitorStore, live: List[dict], now: datetime, config: AlertConfig):
    window = timedelta(minutes=config.spike_window_minutes)
    start = now - window
    new_errors = sum(1 for row in live if row["level"] in ERROR_LEVELS and row["event_time"] >= iso(start))
    if not new_errors:
        return None
    current = store.error_count_between(start, now) + new_errors
    history_start = start - timedelta(hours=config.spike_baseline_hours)
    windows = max(1, int(timedelta(hours=config.spike_baseline_hours) / window))
    baseline = store.error_count_between(history_start, start) / windows
    threshold = max(config.spike_min_errors, config.spike_factor * baseline)
    if current < threshold:
        return None
    return {
        "rule": "error_spike", "key": "all", "severity": "high",
        "title": f"Error spike: {current} errors in {config.spike_window_minutes} min",
        "detail": f"Threshold {threshold:.1f} (baseline {baseline:.2f} per window over {config.spike_baseline_hours} h).",
        "source": ", ".join(sorted({row["source"] for row in live if row["level"] in ERROR_LEVELS})),
        "record_count": current,
    }


def meets_severity(alert: dict, minimum: str) -> bool:
    return SEVERITY_ORDER.get(alert["severity"], 0) >= SEVERITY_ORDER.get(minimum, 0)
