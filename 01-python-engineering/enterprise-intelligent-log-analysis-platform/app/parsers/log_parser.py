import re

from app.models.log_model import LogEntry


LOG_PATTERN = r"(\w+)\s-\s(.*)"


def parse_log_line(line: str):

    match = re.match(LOG_PATTERN, line)

    if match:

        return LogEntry(
            level=match.group(1),
            message=match.group(2)
        )

    return LogEntry(
        level="UNKNOWN",
        message=line.strip()
    )