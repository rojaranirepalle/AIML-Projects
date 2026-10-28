from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import app
from app.monitoring.monitor import LogMonitor
from app.monitoring.store import MonitorStore

TRACE = (
    '[2026-10-03T14:00:05+00:00] main.CRITICAL: SQLSTATE[40001]: Serialization failure: 1213 Deadlock found '
    '{"exception":"[object] (Zend_Db_Statement_Exception(code: 40001): Deadlock at /var/www/html/vendor/Pdo.php:234)\n'
    "[stacktrace]\n#0 /var/www/html/vendor/magento/framework/DB/Statement/Pdo/Mysql.php(91): execute()\n"
    "#1 /var/www/html/app/code/Acme/Checkout/Model/Submit.php(42): save()\n#2 {main}\"} []\n"
)


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "log"
    directory.mkdir()
    (directory / "system.log").write_text(
        "[2026-10-03T13:59:00+00:00] main.INFO: Cron Job a is run [] []\n"
        "[2026-10-03T14:00:01+00:00] main.ERROR: Unable to send mail. Please try again later. [] []\n"
        "[2026-10-03T14:00:02+00:00] main.ERROR: Unable to send mail. Please try again later. [] []\n"
    )
    (directory / "exception.log").write_text(TRACE)
    return directory


@pytest.fixture
def client():
    app.state.monitor = None
    return TestClient(app)


def get(client, log_dir, **params):
    return client.get("/explorer/records", params={"input_path": str(log_dir), **params}).json()


def test_filters_and_facets(client, log_dir):
    body = get(client, log_dir)
    assert body["mode"] == "file" and body["total"] == 4
    assert body["facets"]["level"] == {"ERROR": 2, "INFO": 1, "CRITICAL": 1}
    assert body["items"][0]["time"] > body["items"][-1]["time"]  # newest first

    assert get(client, log_dir, q="send MAIL")["total"] == 2
    assert get(client, log_dir, level="critical,error")["total"] == 3
    assert get(client, log_dir, source="exception.log")["total"] == 1
    assert get(client, log_dir, exception="Zend_Db_Statement_Exception")["total"] == 1
    assert get(client, log_dir, since="2026-10-03T14:00:00", until="2026-10-03T14:00:02")["total"] == 2
    page = get(client, log_dir, limit=1, offset=1, order="asc")
    assert page["items"][0]["level"] == "ERROR" and page["total"] == 4

    template_id = get(client, log_dir, q="send mail")["items"][0]["template_id"]
    assert get(client, log_dir, template_id=template_id)["total"] == 2


def test_record_detail_has_stack_trace_and_fix(client, log_dir):
    record_id = get(client, log_dir, source="exception.log")["items"][0]["id"]
    detail = client.get(f"/explorer/records/{record_id}", params={"input_path": str(log_dir)}).json()
    assert detail["stack_frames"] == 3 and "[stacktrace]" in detail["raw"]
    assert detail["known_issues"][0]["id"] == "db-deadlock"
    assert detail["related"]["template_count"] == 1
    assert client.get("/explorer/records/999", params={"input_path": str(log_dir)}).status_code == 404


def test_missing_path_is_404(client, tmp_path):
    assert client.get("/explorer/records", params={"input_path": str(tmp_path / "nope")}).status_code == 404


def test_live_mode_uses_monitor_store(client, log_dir, tmp_path):
    store = MonitorStore(tmp_path / "m.db")
    monitor = LogMonitor(log_dir, store, flush_after=0, clock=lambda: datetime(2026, 10, 3, 14, 5, tzinfo=timezone.utc))
    monitor.poll_once()
    app.state.monitor = monitor
    try:
        body = client.get("/explorer/records", params={"level": "CRITICAL"}).json()
        assert body["mode"] == "live" and body["total"] == 1
        detail = client.get(f"/explorer/records/{body['items'][0]['id']}").json()
        assert "[stacktrace]" in detail["raw"]
    finally:
        app.state.monitor = None
        store.close()
