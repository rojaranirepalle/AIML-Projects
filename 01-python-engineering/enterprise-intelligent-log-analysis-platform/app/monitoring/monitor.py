"""Live log monitor: tail a directory, parse, template, store, alert, and publish events."""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from drain3.file_persistence import FilePersistence

from app.core.logger import logger
from app.models.log_model import ERROR_LEVELS
from app.monitoring.alerts import AlertConfig, evaluate
from app.monitoring.events import EventBus
from app.monitoring.notifier import Notifier
from app.monitoring.store import MonitorStore, iso, utc_now
from app.monitoring.tailer import LogTailer
from app.parsers.log_parser import parse_log_line
from app.parsers.template_miner import build_miner


class LogMonitor:
    def __init__(
        self,
        log_dir: Path,
        store: MonitorStore,
        notifier: Optional[Notifier] = None,
        bus: Optional[EventBus] = None,
        alert_config: Optional[AlertConfig] = None,
        poll_seconds: float = 2.0,
        flush_after: float = 2.0,
        miner_state_path: Optional[Path] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.log_dir = Path(log_dir)
        if not self.log_dir.is_dir():
            raise FileNotFoundError(f"Log directory not found: {self.log_dir}")
        self.store = store
        self.notifier = notifier or Notifier()
        self.bus = bus or EventBus()
        self.alert_config = alert_config or AlertConfig()
        self.poll_seconds = poll_seconds
        self.clock = clock
        persistence = FilePersistence(str(miner_state_path)) if miner_state_path else None
        self.miner = build_miner(persistence_handler=persistence)
        self.tailer = LogTailer(self.log_dir, flush_after=flush_after, saved_offsets=store.load_offsets())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.started_at: Optional[str] = None
        self.last_poll_at: Optional[str] = None
        self.last_error: Optional[str] = None

    # -- one iteration (synchronous, used by tests and the thread) -------
    def poll_once(self) -> dict:
        now = self.clock()
        ingested_at = iso(now)
        tailed = self.tailer.poll(now.timestamp())
        rows: List[dict] = []
        templates = {}
        for record in tailed:
            try:
                entry = parse_log_line(record.text, source=record.source)
            except ValueError:
                continue
            result = self.miner.add_log_message(entry.message)
            template_id = int(result["cluster_id"])
            templates[template_id] = result["template_mined"]
            rows.append({
                "ingested_at": ingested_at,
                "event_time": iso(entry.timestamp) if entry.timestamp else ingested_at,
                "timestamp": iso(entry.timestamp) if entry.timestamp else None,
                "source": entry.source,
                "channel": entry.channel,
                "level": entry.level,
                "category": entry.category,
                "message": entry.message,
                "exception": entry.exception,
                "stack_frames": entry.stack_frames,
                "template_id": template_id,
                "baseline": 1 if record.baseline else 0,
                "raw": entry.raw,
            })

        alerts = evaluate(self.store, rows, templates, now, self.alert_config)
        self.store.insert_records(rows, templates)
        self.store.save_offsets(self.tailer.offsets())
        saved_alerts = [self.store.add_alert({**alert, "created_at": ingested_at}) for alert in alerts]
        for alert in saved_alerts:
            self.notifier.notify(alert)
            self.bus.publish({"type": "alert", "alert": alert})
        if rows:
            live = [row for row in rows if not row["baseline"]]
            self.bus.publish({
                "type": "records",
                "count": len(rows),
                "live": len(live),
                "errors": sum(1 for row in live if row["level"] in ERROR_LEVELS),
                "sources": sorted({row["source"] for row in rows}),
            })
        self.last_poll_at = ingested_at
        return {"records": len(rows), "baseline": sum(row["baseline"] for row in rows), "alerts": saved_alerts}

    # -- background thread ------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.started_at = iso(self.clock())
        self._thread = threading.Thread(target=self._run, name="log-monitor", daemon=True)
        self._thread.start()
        logger.info("Monitoring %s every %.1fs", self.log_dir, self.poll_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                result = self.poll_once()
                self.last_error = None
                if result["records"]:
                    logger.info("Ingested %d records (%d baseline), %d alert(s)", result["records"], result["baseline"], len(result["alerts"]))
            except Exception as error:  # keep monitoring through transient file/DB errors
                self.last_error = str(error)
                logger.exception("Monitor poll failed")
            self._stop.wait(max(0.0, self.poll_seconds - (time.monotonic() - started)))

    def status(self) -> dict:
        return {
            "running": self.running,
            "log_dir": str(self.log_dir),
            "watched_files": self.tailer.watched_files(),
            "poll_seconds": self.poll_seconds,
            "started_at": self.started_at,
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "email_alerts": self.notifier.email_enabled,
            "stream_clients": self.bus.subscriber_count,
            **self.store.stats(),
        }


def create_monitor(settings, bus: Optional[EventBus] = None) -> LogMonitor:
    """Build a monitor from application settings (``MAGENTO_LOG_DIR`` etc.)."""
    if not settings.magento_log_dir:
        raise ValueError("Set MAGENTO_LOG_DIR (or pass --log-dir) to the Magento var/log directory to monitor.")
    db_path = Path(settings.monitor_db_path)
    store = MonitorStore(db_path)
    return LogMonitor(
        log_dir=Path(settings.magento_log_dir).expanduser(),
        store=store,
        notifier=Notifier.from_settings(settings),
        bus=bus,
        alert_config=AlertConfig(
            cooldown_minutes=settings.alert_cooldown_minutes,
            spike_window_minutes=settings.alert_spike_window_minutes,
            spike_min_errors=settings.alert_spike_min_errors,
            spike_factor=settings.alert_spike_factor,
        ),
        poll_seconds=settings.monitor_poll_seconds,
        miner_state_path=db_path.with_name(db_path.stem + "_templates.bin"),
    )
