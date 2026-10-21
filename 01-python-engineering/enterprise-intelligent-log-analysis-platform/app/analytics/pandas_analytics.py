import pandas as pd

from app.analytics.forecasting import forecast_log_volume
from app.analytics.ml_anomaly import DEFAULT_CONTAMINATION, detect_anomalies


ERROR_LEVELS = {"ERROR", "ERR", "FATAL", "CRITICAL", "SEVERE"}
CRITICAL_LEVELS = {"FATAL", "CRITICAL", "SEVERE"}
WARNING_LEVELS = {"WARN", "WARNING"}
MAX_LISTED = 100


def summarize_templates(df: pd.DataFrame, limit: int = 10) -> list:
    """Rank mined log templates by frequency with their dominant severity."""
    if "template" not in df or df.empty:
        return []
    levels = df["level"].fillna("UNKNOWN").astype(str).str.upper()
    grouped = (
        df.assign(level=levels)
        .groupby(["template_id", "template"], sort=False)
        .agg(count=("level", "size"), level=("level", lambda s: s.mode().iat[0]))
        .reset_index()
        .sort_values(["count", "template_id"], ascending=[False, True])
        .head(limit)
    )
    total = len(df)
    return [
        {
            "template_id": int(row.template_id),
            "template": row.template,
            "count": int(row.count),
            "share": round(row.count / total, 4),
            "level": row.level,
        }
        for row in grouped.itertuples(index=False)
    ]


def generate_summary(df: pd.DataFrame, contamination: float = DEFAULT_CONTAMINATION) -> dict:
    """Compute operational counts and actionable indicators from normalized logs."""
    if "level" not in df or "message" not in df:
        raise ValueError("DataFrame must contain 'level' and 'message' columns")

    total = len(df)
    levels = df["level"].fillna("UNKNOWN").astype(str).str.upper()
    messages = df["message"].fillna("").astype(str)
    top_messages = messages[messages.ne("")].value_counts().head(10).to_dict()
    is_error = levels.isin(ERROR_LEVELS)
    error_count = int(is_error.sum())
    warning_count = int(levels.isin(WARNING_LEVELS).sum())

    # Rule-based severity alerts (vectorized rather than row-by-row).
    flagged = pd.DataFrame({"level": levels, "message": messages})[is_error]
    flagged = flagged.assign(
        reason=flagged["level"].map(lambda level: "critical severity" if level in CRITICAL_LEVELS else "error severity")
    )
    anomalies = [
        {"row": int(index), "level": row.level, "reason": row.reason, "message": row.message}
        for index, row in zip(flagged.index[:MAX_LISTED], flagged.head(MAX_LISTED).itertuples(index=False))
    ]

    return {
        "total_logs": total,
        "severity_distribution": levels.value_counts().to_dict(),
        "category_distribution": df["category"].value_counts().to_dict() if "category" in df else {},
        "error_count": error_count,
        "warning_count": warning_count,
        "error_rate": round(error_count / total, 4) if total else 0.0,
        "top_messages": top_messages,
        "template_count": int(df["template_id"].nunique()) if "template_id" in df else 0,
        "top_templates": summarize_templates(df),
        "anomaly_count": len(flagged),
        "anomalies": anomalies,
        "anomalies_truncated": len(flagged) > MAX_LISTED,
        "ml_anomalies": detect_anomalies(df, contamination=contamination),
        "forecast": forecast_log_volume(df),
    }
