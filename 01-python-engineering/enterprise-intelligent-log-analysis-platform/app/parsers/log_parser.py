import re
from datetime import datetime
from typing import Optional

from app.models.log_model import LogEntry


_LEVELS = r"TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRITICAL|SEVERE"
_LEVEL_LINE = re.compile(rf"^\s*(?P<level>{_LEVELS})\s*[-:]\s*(?P<message>.*?)\s*$", re.I)
_TIMESTAMPED = re.compile(
    rf"^\s*(?P<timestamp>\d{{4}}-\d{{2}}-\d{{2}}[T ][^\s]+)\s+"
    rf"(?P<level>{_LEVELS})\s*[-:]?\s*(?P<message>.*?)\s*$", re.I
)
# Hadoop log4j lines commonly start with YYMMDD HHMMSS PID LEVEL.
_HADOOP = re.compile(
    rf"^\s*(?P<date>\d{{6}})\s+(?P<time>\d{{6}})\s+\d+\s+"
    rf"(?P<level>{_LEVELS})\s+(?P<message>.*?)\s*$", re.I
)


def parse_log_line(line: str, source: Optional[str] = None) -> LogEntry:
    """Parse common application and Hadoop log formats; preserve unknown lines."""
    raw = line.strip()
    if not raw:
        raise ValueError("Cannot parse an empty log line")

    match = _HADOOP.match(raw)
    if match:
        timestamp = datetime.strptime(
            match.group("date") + match.group("time"), "%y%m%d%H%M%S"
        )
        return LogEntry(
            timestamp=timestamp,
            level=match.group("level").upper(),
            message=match.group("message"),
            source=source,
        )

    match = _TIMESTAMPED.match(raw)
    if match:
        timestamp_text = match.group("timestamp").replace("Z", "+00:00")
        try:
            timestamp = datetime.fromisoformat(timestamp_text)
        except ValueError:
            timestamp = None
        return LogEntry(
            timestamp=timestamp,
            level=match.group("level").upper(),
            message=match.group("message") or raw,
            source=source,
        )

    match = _LEVEL_LINE.match(raw)
    if match:
        return LogEntry(
            level=match.group("level").upper(),
            message=match.group("message") or raw,
            source=source,
        )

    # Keep unrecognized records searchable instead of dropping useful evidence.
    return LogEntry(level="UNKNOWN", message=raw, source=source)
