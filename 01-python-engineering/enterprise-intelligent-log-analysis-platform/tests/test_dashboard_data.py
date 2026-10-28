import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.analytics.access_analytics import analyze_access, records_from_raw
from app.analytics.pandas_analytics import hourly_series
from tests.test_access_log import LINES


@pytest.fixture
def client():
    app.state.monitor = None
    return TestClient(app)


def _frame():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-10-03T10:05:00Z", "2026-10-03T10:40:00Z", "2026-10-03T12:10:00Z", "2026-10-03T12:11:00Z"], utc=True
            ),
            "level": ["INFO", "ERROR", "CRITICAL", "WARNING"],
        }
    )


def test_hourly_series_counts_errors_and_warnings_per_hour():
    series = hourly_series(_frame(), hours=4)
    assert [row["time"][11:13] for row in series] == ["09", "10", "11", "12"]  # latest hours, gaps filled with zeros
    assert series[1] == {"time": series[1]["time"], "total": 2, "errors": 1, "warnings": 0}
    assert series[2]["total"] == 0
    assert (series[3]["errors"], series[3]["warnings"]) == (1, 1)  # CRITICAL counts as an error


def test_hourly_series_without_timestamps_is_empty():
    assert hourly_series(pd.DataFrame({"level": ["INFO"], "timestamp": [None]})) == []
    assert hourly_series(pd.DataFrame()) == []


def test_access_hourly_has_requests_5xx_and_p95():
    access = analyze_access(records_from_raw(LINES))
    hour = access["hourly"][-1]
    assert hour["requests"] == 5 and hour["errors_5xx"] == 1 and hour["p95"] is not None


def test_dashboard_data_includes_hourly_series(client, timestamped_log):
    summary = client.get("/dashboard-data", params={"input_path": str(timestamped_log)}).json()["summary"]
    assert len(summary["hourly"]) == 24 and sum(row["total"] for row in summary["hourly"]) == summary["total_logs"]


def test_static_theme_and_pages(client):
    css = client.get("/static/theme.css")
    assert css.status_code == 200 and "--solid" in css.text
    for page in ("/dashboard", "/explorer"):
        assert "/static/theme.css" in client.get(page).text
