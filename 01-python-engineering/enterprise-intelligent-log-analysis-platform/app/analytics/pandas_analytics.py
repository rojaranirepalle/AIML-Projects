import pandas as pd

from app.analytics.forecasting import forecast_log_volume
from app.analytics.ml_anomaly import DEFAULT_CONTAMINATION, detect_anomalies
from app.knowledge.magento import summarize_known_issues


from app.models.log_model import CRITICAL_LEVELS, ERROR_LEVELS, WARNING_LEVELS, expand_levels

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


HOURLY_WINDOW = 24


def hourly_series(df: pd.DataFrame, hours: int = HOURLY_WINDOW) -> list:
    """Errors, warnings and total events per hour for the latest ``hours`` hours of data."""
    if df.empty or "timestamp" not in df or "level" not in df:
        return []
    times = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    valid = times.notna()
    if not valid.any():
        return []
    levels = df["level"].fillna("UNKNOWN").astype(str).str.upper()[valid]
    hour = times[valid].dt.floor("h")
    end = hour.max()
    index = pd.date_range(end - pd.Timedelta(hours=hours - 1), end, freq="h")
    frame = pd.DataFrame({"hour": hour, "error": levels.isin(ERROR_LEVELS), "warning": levels.isin(WARNING_LEVELS)})
    grouped = frame.groupby("hour").agg(total=("error", "size"), errors=("error", "sum"), warnings=("warning", "sum"))
    grouped = grouped.reindex(index, fill_value=0)
    return [
        {"time": stamp.isoformat(), "total": int(row.total), "errors": int(row.errors), "warnings": int(row.warnings)}
        for stamp, row in grouped.iterrows()
    ]


def known_issues(df: pd.DataFrame) -> list:
    """Match every event type (not just the top ones) against the Magento knowledge base."""
    if df.empty:
        return []
    key = "template" if "template" in df else "message"
    frame = df.assign(_key=df[key].fillna("").astype(str))
    agg = {"count": ("_key", "size"), "level": ("level", "first"), "message": ("message", "first")}
    if "exception" in df:
        agg["exception"] = ("exception", "first")
    grouped = frame.groupby("_key", sort=False).agg(**agg).reset_index().rename(columns={"_key": "template"})
    grouped = grouped.astype(object).where(grouped.notna(), None)  # NaN -> None even for all-null columns
    return summarize_known_issues(grouped.to_dict(orient="records"))


def top_values(df: pd.DataFrame, column: str, limit: int = 10) -> dict:
    """Most frequent non-empty values of an optional column."""
    if column not in df:
        return {}
    values = df[column].dropna().astype(str)
    return values[values.ne("")].value_counts().head(limit).to_dict()


def filter_levels(df: pd.DataFrame, spec) -> pd.DataFrame:
    """Keep rows whose level is in ``spec`` (groups such as ``error,warning`` or exact levels)."""
    levels = expand_levels(spec)
    if levels is None or df.empty:
        return df
    return df[df["level"].fillna("UNKNOWN").astype(str).str.upper().isin(levels)]


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
        "channel_distribution": top_values(df, "channel"),
        "top_exceptions": top_values(df, "exception"),
        "template_count": int(df["template_id"].nunique()) if "template_id" in df else 0,
        "top_templates": summarize_templates(df),
        "known_issues": known_issues(df),
        "anomaly_count": len(flagged),
        "anomalies": anomalies,
        "anomalies_truncated": len(flagged) > MAX_LISTED,
        "hourly": hourly_series(df),
        "ml_anomalies": detect_anomalies(df, contamination=contamination),
        "forecast": forecast_log_volume(df),
    }
