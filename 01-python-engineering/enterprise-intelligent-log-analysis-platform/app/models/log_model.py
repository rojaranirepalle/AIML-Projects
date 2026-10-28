from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# Shared severity groups (Monolog/PSR-3 levels plus common log4j/syslog aliases).
CRITICAL_LEVELS = frozenset({"FATAL", "CRITICAL", "SEVERE", "ALERT", "EMERGENCY"})
ERROR_LEVELS = frozenset({"ERROR", "ERR"}) | CRITICAL_LEVELS
WARNING_LEVELS = frozenset({"WARN", "WARNING"})
INFO_LEVELS = frozenset({"INFO", "NOTICE"})
DEBUG_LEVELS = frozenset({"DEBUG", "TRACE"})

# Friendly filter groups used by the dashboard and API (?level=error,warning).
LEVEL_GROUPS = {
    "error": ERROR_LEVELS,
    "warning": WARNING_LEVELS,
    "info": INFO_LEVELS,
    "debug": DEBUG_LEVELS,
    "unknown": frozenset({"UNKNOWN"}),
}
ALL_LEVELS = frozenset().union(*LEVEL_GROUPS.values())


def expand_levels(spec):
    """Turn ``"error,warning"`` or ``"CRITICAL,INFO"`` into a set of levels; ``None`` means no filter."""
    if spec is None or not str(spec).strip():
        return None
    levels = set()
    for token in str(spec).split(","):
        token = token.strip()
        if not token:
            continue
        group = LEVEL_GROUPS.get(token.lower()) or LEVEL_GROUPS.get(token.lower().rstrip("s"))
        if group:
            levels |= group
        elif token.upper() in ALL_LEVELS:
            levels.add(token.upper())
        else:
            raise ValueError(f"Unknown level or group '{token}'. Use error, warning, info, debug or a level such as CRITICAL.")
    return levels


class LogEntry(BaseModel):
    """Normalized representation of one source log record (possibly multi-line)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    timestamp: Optional[datetime] = None
    level: str = "UNKNOWN"
    message: str = Field(min_length=1)
    source: Optional[str] = None
    channel: Optional[str] = None
    exception: Optional[str] = None
    stack_frames: int = 0
    raw: Optional[str] = Field(default=None, repr=False)  # original record text (incl. stack trace)

    @property
    def category(self) -> str:
        level = self.level.upper()
        if level in CRITICAL_LEVELS:
            return "critical"
        if level in ERROR_LEVELS:
            return "error"
        if level in WARNING_LEVELS:
            return "warning"
        if level in {"DEBUG", "TRACE"}:
            return "debug"
        if level in {"INFO", "NOTICE"}:
            return "info"
        return "unknown"
