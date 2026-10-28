import json
import re
from datetime import datetime
from typing import Iterable, Iterator, Optional, Tuple

from app.models.log_model import LogEntry
from app.parsers.access_log import ACCESS_LINE, access_message, level_for_status, parse_access_line


_LEVELS = r"TRACE|DEBUG|INFO|NOTICE|WARN(?:ING)?|ERROR|ERR|FATAL|CRITICAL|SEVERE|ALERT|EMERGENCY"
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
# Adobe Commerce / Magento 2 writes Monolog's line format to var/log/*.log:
#   [2026-10-01T09:15:02.123456+00:00] main.CRITICAL: message {context} [extra]
# Exceptions continue on following lines ([stacktrace], #0 /path:line, ...).
_MONOLOG_START = re.compile(r"^\[\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?\]\s+[\w.-]+\.[A-Z]+:")
_MONOLOG = re.compile(
    r"^\[(?P<timestamp>\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)\]\s+"
    r"(?P<channel>[\w.-]+)\.(?P<level>DEBUG|INFO|NOTICE|WARNING|ERROR|CRITICAL|ALERT|EMERGENCY):\s?"
    r"(?P<body>.*)$",
    re.S,
)
# Monolog appends "%context% %extra%": JSON objects or empty arrays.
_CONTEXT_TAIL = re.compile(r"^(?P<message>.*?)\s(?P<context>\{.*\}|\[\])\s(?P<extra>\{.*\}|\[\])\s*$", re.S)
_EXCEPTION_CLASS = re.compile(r"\[object\]\s*\((?P<cls>[A-Za-z_\\][\w\\]*)\(code:")
_PHP_EXCEPTION_PREFIX = re.compile(r"^(?P<cls>(?:[A-Za-z_\\][\w\\]*)?(?:Exception|Error)):\s")
_STACK_FRAME = re.compile(r"^#\d+\s", re.M)


# Keys dropped when a message is itself a JSON object (e.g. Commerce Data Export):
# they vary per run and would split one event type into many templates. "caller"
# can also contain CLI arguments such as --db-password.
_VOLATILE_JSON_KEYS = {"pid", "caller", "elapsed", "time", "timestamp", "duration", "memory", "realmem"}


def flatten_json_message(message: str) -> str:
    """Render a JSON-object message as ``key=value`` pairs without volatile keys."""
    if not message.startswith("{"):
        return message
    try:
        data = json.loads(message)
    except ValueError:
        return message
    if not isinstance(data, dict) or not data:
        return message
    parts = [
        f"{key}={value if isinstance(value, (str, int, float, bool)) or value is None else json.dumps(value)}"
        for key, value in data.items()
        if key.lower() not in _VOLATILE_JSON_KEYS
    ]
    return " ".join(parts) or message


def is_record_start(line: str) -> bool:
    """True when ``line`` begins a new record in any supported format."""
    return bool(
        _MONOLOG_START.match(line)
        or ACCESS_LINE.match(line)
        or _HADOOP.match(line)
        or _TIMESTAMPED.match(line)
        or _LEVEL_LINE.match(line)
    )


def iter_records(lines: Iterable[str]) -> Iterator[Tuple[int, str]]:
    """Yield ``(first_line_number, record_text)``, joining Monolog continuation lines.

    Lines that do not start a record are attached to the preceding Monolog
    record (stack traces, wrapped JSON). Outside Monolog they stay standalone so
    unrecognized evidence is never silently merged.
    """
    buffer: list = []
    start = 0
    in_monolog = False
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if buffer and in_monolog and not is_record_start(line):
            buffer.append(line)
            continue
        if buffer:
            yield start, "\n".join(buffer)
        buffer, start = [line], number
        in_monolog = bool(_MONOLOG_START.match(line))
    if buffer:
        yield start, "\n".join(buffer)


def _parse_monolog(match: re.Match, source: Optional[str]) -> LogEntry:
    body = match.group("body")
    first_line, _, _ = body.partition("\n")
    tail = _CONTEXT_TAIL.match(body)
    message = tail.group("message") if tail else first_line
    message = message.split("\n", 1)[0].strip() or first_line.strip() or body.strip()
    message = flatten_json_message(message)

    exception = None
    found = _EXCEPTION_CLASS.search(body) or _PHP_EXCEPTION_PREFIX.match(message)
    if found:
        exception = found.group("cls").replace("\\\\", "\\")

    try:
        timestamp = datetime.fromisoformat(match.group("timestamp").replace("Z", "+00:00"))
    except ValueError:
        timestamp = None
    return LogEntry(
        timestamp=timestamp,
        level=match.group("level").upper(),
        message=message,
        source=source,
        channel=match.group("channel"),
        exception=exception,
        stack_frames=len(_STACK_FRAME.findall(body)),
        raw=match.group(0)[:MAX_RAW_CHARS],
    )


MAX_RAW_CHARS = 20000


def parse_log_line(line: str, source: Optional[str] = None) -> LogEntry:
    """Parse Magento/Monolog, Hadoop and common application formats; preserve unknown lines.

    ``line`` may be a multi-line record produced by :func:`iter_records`.
    """
    raw = line.strip()
    if not raw:
        raise ValueError("Cannot parse an empty log line")

    entry = _parse(raw, source)
    if entry.raw is None:
        entry.raw = raw[:MAX_RAW_CHARS]
    return entry


def _parse(raw: str, source: Optional[str]) -> LogEntry:
    match = _MONOLOG.match(raw)
    if match:
        return _parse_monolog(match, source)

    access = parse_access_line(raw) if raw[:1].isalnum() and '"' in raw else None
    if access:
        return LogEntry(
            timestamp=access.timestamp,
            level=level_for_status(access.status),
            message=access_message(access),
            source=source,
            channel="nginx",
        )

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
