from typing import List

import pandas as pd

from app.models.log_model import LogEntry


COLUMNS = ["timestamp", "level", "category", "channel", "message", "exception", "stack_frames", "source", "raw"]


def logs_to_dataframe(logs: List[LogEntry]) -> pd.DataFrame:
    """Convert normalized entries to a stable-schema dataframe, including when empty."""
    rows = [
        {
            "timestamp": log.timestamp,
            "level": log.level,
            "category": log.category,
            "channel": log.channel,
            "message": log.message,
            "exception": log.exception,
            "stack_frames": log.stack_frames,
            "source": log.source,
            "raw": log.raw,
        }
        for log in logs
    ]
    return pd.DataFrame(rows, columns=COLUMNS)
