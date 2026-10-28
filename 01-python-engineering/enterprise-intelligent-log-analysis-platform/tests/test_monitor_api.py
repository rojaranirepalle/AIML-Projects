from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.monitoring.monitor import LogMonitor
from app.monitoring.store import MonitorStore


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def live(tmp_path):
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    (log_dir / "system.log").write_text("[2026-10-25T07:00:00+00:00] main.INFO: Cron Job a is run [] []\n")
    store = MonitorStore(tmp_path / "m.db")
    monitor = LogMonitor(log_dir, store, flush_after=0, clock=lambda: datetime(2026, 10, 25, 7, 1, tzinfo=timezone.utc))
    monitor.poll_once()
    with (log_dir / "system.log").open("a") as handle:
        handle.write("[2026-10-25T07:00:30+00:00] main.ALERT: Disk usage at 97% [] []\n")
    monitor.poll_once()
    app.state.monitor = monitor
    yield monitor
    app.state.monitor = None
    store.close()


def test_status_when_not_running(client):
    app.state.monitor = None
    body = client.get("/monitor/status").json()
    assert body["running"] is False
    assert client.get("/monitor/alerts").status_code == 409


def test_live_endpoints(client, live):
    status = client.get("/monitor/status").json()
    assert status["records"] == 2 and status["watched_files"] == ["system.log"]

    snapshot = client.get("/monitor/dashboard-data").json()
    assert snapshot["mode"] == "live" and snapshot["total"] == 2
    assert snapshot["summary"]["severity_distribution"] == {"INFO": 1, "ALERT": 1}
    assert snapshot["alerts"][0]["rule"] == "critical_level"

    alert_id = client.get("/monitor/alerts", params={"open_only": True}).json()["items"][0]["id"]
    assert client.post(f"/monitor/alerts/{alert_id}/ack").json()["acknowledged"] is True
    assert client.get("/monitor/alerts", params={"open_only": True}).json()["items"] == []
    assert client.post("/monitor/alerts/999/ack").status_code == 404

    records = client.get("/monitor/records", params={"level": "alert"}).json()["items"]
    assert len(records) == 1 and records[0]["template"].startswith("Disk usage")


def test_directory_input_on_classic_endpoint(client, live):
    body = client.get("/summary", params={"input_path": str(live.log_dir)}).json()
    assert body["source_files"] == ["system.log"] and body["total_logs"] == 2


def test_live_dashboard_level_filter(client, live):
    snapshot = client.get("/monitor/dashboard-data", params={"level": "error"}).json()
    assert snapshot["summary"]["severity_distribution"] == {"ALERT": 1}
    assert snapshot["summary"]["level_filter"]["total"] == 2
    assert client.get("/monitor/dashboard-data", params={"level": "nope"}).status_code == 400
