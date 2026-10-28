import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.models.log_model import expand_levels

LOG = (
    "[2026-10-03T14:00:00+00:00] main.INFO: Cron Job a is run [] []\n"
    "[2026-10-03T14:00:01+00:00] main.DEBUG: cache_invalidate: [] []\n"
    "[2026-10-03T14:00:02+00:00] main.WARNING: Session size of 300000 exceeded allowed session max size of 256000. [] []\n"
    "[2026-10-03T14:00:03+00:00] main.ERROR: Unable to send mail. Please try again later. [] []\n"
    "[2026-10-03T14:00:04+00:00] main.CRITICAL: Could not ping search engine: No alive nodes found in your cluster [] []\n"
)


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "system.log"
    path.write_text(LOG)
    return path


@pytest.fixture
def client():
    app.state.monitor = None
    return TestClient(app)


def test_expand_levels_accepts_groups_plurals_and_exact_levels():
    assert expand_levels(None) is None and expand_levels(" ") is None
    assert {"ERROR", "CRITICAL", "ALERT"} <= expand_levels("error")
    assert expand_levels("warnings") == {"WARN", "WARNING"}
    assert expand_levels("info,CRITICAL") == {"INFO", "NOTICE", "CRITICAL"}
    with pytest.raises(ValueError):
        expand_levels("loud")


def test_dashboard_data_filters_every_section(client, log_file):
    body = client.get("/dashboard-data", params={"input_path": str(log_file), "level": "error"}).json()
    summary = body["summary"]
    assert summary["total_logs"] == 2 and body["total"] == 2
    assert summary["severity_distribution"] == {"ERROR": 1, "CRITICAL": 1}
    assert summary["level_filter"] == {"spec": "error", "matched": 2, "total": 5}
    assert {issue["id"] for issue in summary["known_issues"]} == {"mail-send-failed", "search-engine-unavailable"}
    assert {item["level"] for item in body["items"]} == {"ERROR", "CRITICAL"}

    warnings = client.get("/dashboard-data", params={"input_path": str(log_file), "level": "warning"}).json()["summary"]
    assert [issue["id"] for issue in warnings["known_issues"]] == ["session-size-exceeded"]

    unfiltered = client.get("/dashboard-data", params={"input_path": str(log_file)}).json()["summary"]
    assert unfiltered["total_logs"] == 5 and "level_filter" not in unfiltered


def test_invalid_level_is_400(client, log_file):
    assert client.get("/dashboard-data", params={"input_path": str(log_file), "level": "loud"}).status_code == 400


def test_explorer_accepts_level_groups(client, log_file):
    body = client.get("/explorer/records", params={"input_path": str(log_file), "level": "error,warning"}).json()
    assert body["total"] == 3
