import pandas as pd

from app.analytics.forecasting import forecast_log_volume
from app.analytics.ml_anomaly import detect_anomalies
from app.analytics.pandas_analytics import generate_summary
from app.parsers.template_miner import add_templates


def make_df(levels, messages, timestamps=None):
    df = pd.DataFrame({"level": levels, "message": messages})
    if timestamps is not None:
        df["timestamp"] = timestamps
    return add_templates(df)


def test_summary_counts_and_rule_alerts():
    df = make_df(
        ["INFO", "ERROR", "FATAL", "WARNING", "INFO"],
        ["user 1 logged in", "db down", "disk failure", "memory high", "user 2 logged in"],
    )
    summary = generate_summary(df)
    assert summary["total_logs"] == 5
    assert summary["error_count"] == 2
    assert summary["warning_count"] == 1
    assert summary["error_rate"] == 0.4
    assert [a["reason"] for a in summary["anomalies"]] == ["error severity", "critical severity"]
    assert summary["anomaly_count"] == 2
    assert summary["template_count"] == 4  # the two login lines share a template
    assert summary["top_templates"][0]["count"] == 2


def test_summary_requires_level_and_message():
    try:
        generate_summary(pd.DataFrame({"x": [1]}))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_ml_reports_small_batches_as_unavailable():
    result = detect_anomalies(make_df(["INFO"] * 3, ["a", "b", "c"]))
    assert result["available"] is False and result["anomaly_count"] == 0


def test_ml_flags_rare_severe_event():
    messages = [f"heartbeat from node {i}" for i in range(60)] + ["kernel panic on node 7"]
    levels = ["INFO"] * 60 + ["FATAL"]
    result = detect_anomalies(make_df(levels, messages), contamination=0.02)
    assert result["available"] is True
    assert result["anomalous_templates"][0]["template"].startswith("kernel panic")
    assert any(a["row"] == 60 for a in result["anomalies"])


def test_forecast_needs_timestamps():
    assert forecast_log_volume(pd.DataFrame({"level": ["INFO"], "timestamp": [None]}))["available"] is False


def test_forecast_hourly_trend():
    timestamps = pd.to_datetime(
        ["2024-01-01 00:10"] * 1 + ["2024-01-01 01:10"] * 2 + ["2024-01-01 02:10"] * 3
    )
    df = pd.DataFrame({"timestamp": timestamps, "level": ["INFO"] * 6})
    forecast = forecast_log_volume(df)
    assert forecast["available"] is True
    assert forecast["frequency"] == "hourly"
    assert forecast["trend"] == "increasing"
    assert forecast["predicted_log_count"] == 4.0
