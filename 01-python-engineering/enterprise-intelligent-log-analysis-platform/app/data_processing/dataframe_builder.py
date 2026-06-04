import pandas as pd

from app.models.log_model import LogEntry


def logs_to_dataframe(logs: list[LogEntry]):

    data = []

    for log in logs:

        data.append(
            {
                "level": log.level,
                "message": log.message
            }
        )

    return pd.DataFrame(data)