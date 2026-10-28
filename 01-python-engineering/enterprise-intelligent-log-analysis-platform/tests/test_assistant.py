from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import assistant
from app.api import app
from app.assistant import suspect_frame
from app.config.settings import settings
from app.monitoring.monitor import LogMonitor
from app.monitoring.store import MonitorStore
from tests.test_explorer import TRACE


@pytest.fixture
def log_dir(tmp_path):
    directory = tmp_path / "log"
    directory.mkdir()
    (directory / "system.log").write_text(
        "[2026-10-03T14:00:01+00:00] main.WARNING: Failed login attempt for customer asha.12@example.com from 203.0.113.7 [] []\n"
        "[2026-10-03T14:00:02+00:00] main.CRITICAL: Could not ping search engine: No alive nodes found in your cluster [] []\n"
    )
    (directory / "exception.log").write_text(TRACE)
    return directory


@pytest.fixture
def client(monkeypatch):
    app.state.monitor = None
    monkeypatch.setattr(settings, "incident_summary_enabled", False)
    return TestClient(app)


def record_id(client, log_dir, **params):
    return client.get("/explorer/records", params={"input_path": str(log_dir), **params}).json()["items"][0]["id"]


def test_suspect_frame_prefers_project_code():
    raw = "x\n#0 /var/www/html/vendor/symfony/console/Command/Command.php(341): run()\n#1 /var/www/html/vendor/magento/module-sales/Model/Order.php(10): a()\n#2 /var/www/html/app/code/Acme/Foo/Model/Bar.php(7): b()"
    assert suspect_frame(raw) == "/var/www/html/app/code/Acme/Foo/Model/Bar.php:7"
    assert suspect_frame(raw.rsplit("\n", 1)[0]) == "/var/www/html/vendor/magento/module-sales/Model/Order.php:10"
    assert suspect_frame("no trace") is None


def test_rule_based_explanation_for_record(client, log_dir):
    body = client.post("/assistant/explain", json={"record_id": record_id(client, log_dir, source="exception.log"), "input_path": str(log_dir)}).json()
    assert body["mode"] == "rules" and "disabled" in body["llm_unavailable_reason"]
    assert body["known_issues"][0]["id"] == "db-deadlock"
    assert body["evidence"]["event"]["suspect_frame"] == "/var/www/html/app/code/Acme/Checkout/Model/Submit.php:42"
    for section in ("Summary", "Likely cause", "Evidence", "Check next", "Fix"):
        assert section in body["answer"]
    # The search outage two seconds earlier is reported as co-occurring.
    assert any("search engine" in item["event"] for item in body["evidence"]["around_the_same_time"]["other_problems"])


def test_question_mode(client, log_dir):
    body = client.post("/assistant/explain", json={"question": "Why is search failing?", "input_path": str(log_dir)}).json()
    assert body["target"]["type"] == "question"
    assert "Search engine unreachable" in body["answer"]


def test_llm_mode_receives_only_masked_evidence(client, log_dir, monkeypatch):
    captured = {}

    def fake_complete(system_prompt, user_content, max_tokens=1200):
        captured["content"] = user_content
        return "Summary\n- Login failures and a search outage."

    monkeypatch.setattr(assistant, "availability", lambda: None)
    monkeypatch.setattr(assistant, "complete", fake_complete)
    body = client.post("/assistant/explain", json={"question": "What happened at 14:00?", "input_path": str(log_dir)}).json()
    assert body["mode"] == "llm" and body["answer"].startswith("Summary")
    assert "asha.12@example.com" not in captured["content"] and "203.0.113.7" not in captured["content"]


def test_llm_failure_falls_back_to_rules(client, log_dir, monkeypatch):
    def failing(*args, **kwargs):
        raise assistant.LLMError("AI provider request failed: timeout")

    monkeypatch.setattr(assistant, "availability", lambda: None)
    monkeypatch.setattr(assistant, "complete", failing)
    body = client.post("/assistant/explain", json={"question": "status?", "input_path": str(log_dir)}).json()
    assert body["mode"] == "rules" and "timeout" in body["llm_unavailable_reason"]


def test_alert_explanation_in_live_mode(client, log_dir, tmp_path):
    store = MonitorStore(tmp_path / "m.db")
    monitor = LogMonitor(log_dir, store, flush_after=0, clock=lambda: datetime(2026, 10, 3, 14, 5, tzinfo=timezone.utc))
    monitor.poll_once()  # baseline
    with (log_dir / "system.log").open("a") as handle:
        handle.write('[2026-10-03T14:04:00+00:00] main.CRITICAL: Import failed {"exception":"[object] (Acme\\\\Import\\\\RowException(code: 0): bad row at /x.php:1)"} []\n')
    alert = monitor.poll_once()["alerts"][0]
    app.state.monitor = monitor
    try:
        body = client.post("/assistant/explain", json={"alert_id": alert["id"]}).json()
        assert body["target"]["type"] == "alert" and body["evidence"]["event"]["exception"] == "Acme\\Import\\RowException"
        assert client.post("/assistant/explain", json={"alert_id": 999}).status_code == 404
    finally:
        app.state.monitor = None
        store.close()


def test_request_needs_a_target(client):
    assert client.post("/assistant/explain", json={}).status_code == 422


def test_nearby_issue_is_not_reported_as_the_cause(client, log_dir):
    with (log_dir / "system.log").open("a") as handle:
        handle.write('[2026-10-03T14:00:03+00:00] main.CRITICAL: Acme loyalty sync failed {"exception":"[object] (Acme\\\\Loyalty\\\\SyncException(code: 0): timeout at /x.php:1)"} []\n')
    body = client.post("/assistant/explain", json={"record_id": record_id(client, log_dir, q="loyalty"), "input_path": str(log_dir)}).json()
    assert body["known_issues"] == []
    assert {issue["id"] for issue in body["related_issues"]} >= {"search-engine-unavailable"}
    assert "No known Magento pattern matches this event itself" in body["answer"]
    assert "context, not necessarily the cause" in body["answer"]
