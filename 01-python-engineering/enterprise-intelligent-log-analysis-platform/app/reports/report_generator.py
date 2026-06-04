import pandas as pd


def export_report(df: pd.DataFrame):

    df.to_csv(
        "logs/log_summary.csv",
        index=False
    )