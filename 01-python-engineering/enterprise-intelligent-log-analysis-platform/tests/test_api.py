import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.config.settings import settings


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_summary_and_dashboard_data(client, timestamped_log):
    summary = client.get("/summary", params={"input_path": str(timestamped_log)}).json()
    assert summary["total_logs"] == 37
    assert summary["error_count"] == 1

    snapshot = client.get("/dashboard-data", params={"input_path": str(timestamped_log)}).json()
    assert snapshot["total"] == 37 and len(snapshot["items"]) == 37


def test_logs_pagination(client, timestamped_log):
    body = client.post("/logs", json={"input_path": str(timestamped_log), "offset": 30, "limit": 5}).json()
    assert body["total"] == 37 and len(body["items"]) == 5 and body["offset"] == 30


def test_logs_limit_is_validated(client, timestamped_log):
    response = client.post("/logs", json={"input_path": str(timestamped_log), "limit": 5000})
    assert response.status_code == 422


def test_analyze_writes_reports(client, mixed_log, tmp_path):
    report, summary = tmp_path / "r.csv", tmp_path / "s.json"
    response = client.post(
        "/analyze", json={"input_path": str(mixed_log), "report_path": str(report), "summary_path": str(summary)}
    )
    assert response.status_code == 200
    assert report.is_file() and summary.is_file()


def test_missing_file_returns_404(client, tmp_path):
    response = client.get("/summary", params={"input_path": str(tmp_path / "nope.log")})
    assert response.status_code == 404


def test_incident_summary_disabled_returns_409(client, mixed_log, monkeypatch):
    monkeypatch.setattr(settings, "incident_summary_enabled", False)
    response = client.post("/incident-summary", json={"input_path": str(mixed_log)})
    assert response.status_code == 409


def test_dashboard_page_served(client):
    response = client.get("/dashboard")
    assert response.status_code == 200 and "Needs attention" in response.text and "Top event types" in response.text
