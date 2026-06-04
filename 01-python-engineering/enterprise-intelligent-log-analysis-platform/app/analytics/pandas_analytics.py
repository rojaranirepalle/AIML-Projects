import pandas as pd


def generate_summary(df: pd.DataFrame):

    severity_distribution = (
        df["level"]
        .value_counts()
        .to_dict()
    )

    top_messages = (
        df["message"]
        .value_counts()
        .head(5)
        .to_dict()
    )

    return {
        "severity_distribution": severity_distribution,
        "top_messages": top_messages
    }