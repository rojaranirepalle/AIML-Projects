from collections import Counter

from app.models.log_model import LogEntry


def analyze_logs(logs: list[LogEntry]):

    level_counter = Counter()
    message_counter = Counter()

    for log in logs:

        level_counter[log.level] += 1
        message_counter[log.message] += 1

    return {
        "log_levels": dict(level_counter),
        "top_messages": message_counter.most_common(5)
    }