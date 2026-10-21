"""Simple baseline forecast for timestamped log volume and error volume."""

import numpy as np
import pandas as pd


def forecast_log_volume(df: pd.DataFrame) -> dict:
    """Extrapolate the recent linear trend by one time bucket, when data permits."""
    if "timestamp" not in df or df["timestamp"].notna().sum() < 3:
        return {"available": False, "reason": "At least three timestamped records are required."}

    timestamps = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dropna()
    if len(timestamps) < 3:
        return {"available": False, "reason": "At least three valid timestamps are required."}

    span = timestamps.max() - timestamps.min()
    frequency = "h" if span <= pd.Timedelta(days=3) else "D"
    counts = timestamps.dt.floor(frequency).value_counts().sort_index()
    full_range = pd.date_range(counts.index[0], counts.index[-1], freq=frequency)
    counts = counts.reindex(full_range, fill_value=0)
    if len(counts) < 3:
        return {
            "available": False,
            "reason": "At least three distinct time buckets are required for a forecast.",
            "frequency": "hourly" if frequency == "h" else "daily",
        }

    x_values = list(range(len(counts)))
    slope, intercept = np.polyfit(x_values, counts.to_numpy(dtype=float), 1)
    next_count = max(0.0, float(slope * len(counts) + intercept))

    error_forecast = None
    if "level" in df:
        normalized = df["level"].fillna("UNKNOWN").astype(str).str.upper()
        error_timestamps = pd.to_datetime(
            df.loc[normalized.isin({"ERROR", "ERR", "FATAL", "CRITICAL", "SEVERE"}), "timestamp"],
            utc=True,
            errors="coerce",
        ).dropna()
        error_counts = error_timestamps.dt.floor(frequency).value_counts().sort_index()
        error_counts = error_counts.reindex(counts.index, fill_value=0)
        if len(error_counts) >= 3:
            error_slope, error_intercept = np.polyfit(
                range(len(error_counts)), error_counts.to_numpy(dtype=float), 1
            )
            error_forecast = round(max(0.0, float(error_slope * len(error_counts) + error_intercept)), 2)

    return {
        "available": True,
        "method": "linear_trend_baseline",
        "frequency": "hourly" if frequency == "h" else "daily",
        "buckets_analyzed": len(counts),
        "next_bucket": str(counts.index[-1] + pd.tseries.frequencies.to_offset(frequency)),
        "predicted_log_count": round(next_count, 2),
        "predicted_error_count": error_forecast,
        "trend": "increasing" if slope > 0.05 else "decreasing" if slope < -0.05 else "stable",
    }
