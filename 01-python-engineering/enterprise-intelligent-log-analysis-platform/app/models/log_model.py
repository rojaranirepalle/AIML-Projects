from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LogEntry(BaseModel):
    """Normalized representation of one source log line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    timestamp: Optional[datetime] = None
    level: str = "UNKNOWN"
    message: str = Field(min_length=1)
    source: Optional[str] = None

    @property
    def category(self) -> str:
        level = self.level.upper()
        if level in {"FATAL", "CRITICAL", "SEVERE"}:
            return "critical"
        if level in {"ERROR", "ERR"}:
            return "error"
        if level in {"WARN", "WARNING"}:
            return "warning"
        if level in {"DEBUG", "TRACE"}:
            return "debug"
        if level in {"INFO", "NOTICE"}:
            return "info"
        return "unknown"
