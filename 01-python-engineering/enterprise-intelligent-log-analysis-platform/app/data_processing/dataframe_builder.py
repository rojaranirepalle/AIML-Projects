from typing import List

import pandas as pd

from app.models.log_model import LogEntry


COLUMNS = ["timestamp", "level", "category", "message", "source"]


def logs_to_dataframe(logs: List[LogEntry]) -> pd.DataFrame:
    """Convert normalized entries to a stable-schema dataframe, including when empty."""
    rows = [
        {
            "timestamp": log.timestamp,
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "source": log.source,
        }
        for log in logs
    ]
    return pd.DataFrame(rows, columns=COLUMNS)
