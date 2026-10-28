from datetime import datetime, timedelta, timezone

import pytest

from app.monitoring.alerts import AlertConfig
from app.monitoring.monitor import LogMonitor
from app.monitoring.notifier import Notifier
from app.monitoring.store import MonitorStore

START = datetime(2026, 10, 25, 7, 0, tzinfo=timezone.utc)


def mline(message, level="INFO", at=START):
    return f"[{at.isoformat()}] main.{level}: {message} [] []\n"


def exception_line(cls, message, at):
    return f'[{at.isoformat()}] main.CRITICAL: {message} {{"exception":"[object] ({cls}(code: 0): {message} at /x.php:1)"}} []\n'


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


@pytest.fixture
def setup(tmp_path):
    log_dir = tmp_path / "var" / "log"
    log_dir.mkdir(parents=True)
    (log_dir / "system.log").write_text(mline("Cron Job a is run") + mline("old failure", "ERROR"))
    clock = Clock()
    store = MonitorStore(tmp_path / "monitor.db")
    monitor = LogMonitor(log_dir, store, flush_after=0, clock=clock,
                         alert_config=AlertConfig(cooldown_minutes=15, spike_min_errors=5, spike_factor=3))
    yield monitor, log_dir / "system.log", clock
    store.close()


def write(path, text):
    with path.open("a") as handle:
        handle.write(text)


def test_history_is_stored_without_alerts(setup):
    monitor, _, _ = setup
    result = monitor.poll_once()
    assert result == {"records": 2, "baseline": 2, "alerts": []}
    assert monitor.store.stats()["records"] == 2


def test_rules_fire_once_and_respect_known_events(setup):
    monitor, log, clock = setup
    monitor.poll_once()
    clock.now += timedelta(minutes=1)
    write(log, mline("old failure", "ERROR", clock.now))  # known error type: no alert
    write(log, exception_line("Acme\\\\Catalog\\\\ImportException", "Import failed", clock.now))
    write(log, mline("Disk usage at 97%", "ALERT", clock.now))
    rules = sorted(alert["rule"] for alert in monitor.poll_once()["alerts"])
    assert rules == ["critical_level", "new_exception"]

    clock.now += timedelta(minutes=1)
    write(log, exception_line("Acme\\\\Catalog\\\\ImportException", "Import failed", clock.now))
    assert monitor.poll_once()["alerts"] == []  # class is now known


def test_error_spike_and_cooldown(setup):
    monitor, log, clock = setup
    monitor.poll_once()
    clock.now += timedelta(minutes=2)
    write(log, "".join(mline("old failure", "ERROR", clock.now) for _ in range(6)))
    assert [a["rule"] for a in monitor.poll_once()["alerts"]] == ["error_spike"]

    clock.now += timedelta(minutes=1)
    write(log, "".join(mline("old failure", "ERROR", clock.now) for _ in range(6)))
    assert monitor.poll_once()["alerts"] == []  # within the 15-minute cooldown


def test_offsets_survive_restart(setup, tmp_path):
    monitor, log, clock = setup
    monitor.poll_once()
    db_path = monitor.store.path
    monitor.store.close()

    write(log, mline("while stopped", "INFO", clock.now))
    store = MonitorStore(db_path)
    restarted = LogMonitor(log.parent, store, flush_after=0, clock=clock)
    assert restarted.poll_once()["records"] == 1
    assert store.stats()["records"] == 3
    monitor.store = store  # let the fixture close the live store


def test_second_monitor_on_same_database_is_refused(setup):
    monitor, _, _ = setup
    with pytest.raises(RuntimeError, match="Another monitor"):
        MonitorStore(monitor.store.path)


def test_acknowledge_and_records_frame(setup):
    monitor, log, clock = setup
    monitor.poll_once()
    write(log, mline("Disk usage at 99%", "EMERGENCY", clock.now))
    alert = monitor.poll_once()["alerts"][0]
    assert monitor.store.acknowledge(alert["id"]) is True
    assert monitor.store.list_alerts(unacknowledged_only=True) == []
    assert monitor.store.stats()["open_alerts"] == 0
    frame = monitor.store.records_frame()
    assert list(frame["level"]) == ["INFO", "ERROR", "EMERGENCY"]
    assert frame["template"].notna().all()


def test_alert_email_masks_customer_data():
    notifier = Notifier(email_enabled=True, recipient="ops@example.com")
    email = notifier.build_email({
        "rule": "new_error_template", "severity": "medium", "title": "New error type",
        "detail": "Failed login for asha@example.com from 203.0.113.9", "source": "system.log",
    })
    body = email.get_content()
    assert "asha@example.com" not in body and "<EMAIL>" in body and "<IP>" in body
    assert email["To"] == "ops@example.com"
