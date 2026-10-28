"""SQLite persistence for monitored records, templates, file offsets and alerts."""

import sqlite3
import threading

try:  # POSIX advisory lock; Windows falls back to no lock
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

from app.models.log_model import ERROR_LEVELS

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY,
    ingested_at TEXT NOT NULL,
    event_time TEXT NOT NULL,
    timestamp TEXT,
    source TEXT,
    channel TEXT,
    level TEXT NOT NULL,
    category TEXT,
    message TEXT NOT NULL,
    exception TEXT,
    stack_frames INTEGER DEFAULT 0,
    template_id INTEGER,
    baseline INTEGER DEFAULT 0,
    raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_event_time ON records(event_time);
CREATE INDEX IF NOT EXISTS idx_records_level ON records(level);
CREATE TABLE IF NOT EXISTS templates (
    template_id INTEGER PRIMARY KEY,
    template TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS exceptions (
    exception TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS file_offsets (
    path TEXT PRIMARY KEY,
    inode INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    rule TEXT NOT NULL,
    key TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    source TEXT,
    record_count INTEGER DEFAULT 1,
    acknowledged INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_rule_key ON alerts(rule, key, created_at);
"""

RECORD_COLUMNS = [
    "ingested_at", "event_time", "timestamp", "source", "channel", "level", "category",
    "message", "exception", "stack_frames", "template_id", "baseline", "raw",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


class MonitorStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._lock_file = None
        if str(path) != ":memory:" and fcntl is not None:
            # Two monitors on one database would ingest the same lines twice.
            self._lock_file = open(self.path.with_suffix(self.path.suffix + ".lock"), "w")
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self._lock_file.close()
                raise RuntimeError(f"Another monitor is already using {self.path}. Stop it first.")
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the monitor thread
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was created."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "raw" not in columns:
            self._conn.execute("ALTER TABLE records ADD COLUMN raw TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
        if self._lock_file is not None:
            self._lock_file.close()  # releases the flock
            self._lock_file = None

    # -- writes ---------------------------------------------------------
    def insert_records(self, rows: List[dict], templates: Dict[int, str]) -> None:
        """Insert parsed records and update template/exception registries in one transaction."""
        if not rows:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                f"INSERT INTO records ({', '.join(RECORD_COLUMNS)}) VALUES ({', '.join('?' * len(RECORD_COLUMNS))})",
                [tuple(row.get(column) for column in RECORD_COLUMNS) for row in rows],
            )
            for row in rows:
                is_error = 1 if row["level"] in ERROR_LEVELS else 0
                self._conn.execute(
                    """INSERT INTO templates (template_id, template, first_seen, last_seen, count, error_count)
                       VALUES (?, ?, ?, ?, 1, ?)
                       ON CONFLICT(template_id) DO UPDATE SET template=excluded.template,
                         last_seen=excluded.last_seen, count=count+1, error_count=error_count+excluded.error_count""",
                    (row["template_id"], templates[row["template_id"]], row["event_time"], row["event_time"], is_error),
                )
                if row.get("exception"):
                    self._conn.execute(
                        """INSERT INTO exceptions (exception, first_seen, last_seen, count) VALUES (?, ?, ?, 1)
                           ON CONFLICT(exception) DO UPDATE SET last_seen=excluded.last_seen, count=count+1""",
                        (row["exception"], row["event_time"], row["event_time"]),
                    )

    def save_offsets(self, offsets: Dict[str, Tuple[int, int]]) -> None:
        now = iso(utc_now())
        with self._lock, self._conn:
            self._conn.executemany(
                """INSERT INTO file_offsets (path, inode, offset, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET inode=excluded.inode, offset=excluded.offset, updated_at=excluded.updated_at""",
                [(path, inode, offset, now) for path, (inode, offset) in offsets.items()],
            )

    def add_alert(self, alert: dict) -> dict:
        created_at = alert.get("created_at") or iso(utc_now())
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """INSERT INTO alerts (created_at, rule, key, severity, title, detail, source, record_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (created_at, alert["rule"], alert["key"], alert["severity"], alert["title"],
                 alert.get("detail"), alert.get("source"), alert.get("record_count", 1)),
            )
        return {**alert, "id": cursor.lastrowid, "created_at": created_at, "acknowledged": False}

    def acknowledge(self, alert_id: int) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        return cursor.rowcount > 0

    # -- reads ----------------------------------------------------------
    def load_offsets(self) -> Dict[str, Tuple[int, int]]:
        with self._lock:
            rows = self._conn.execute("SELECT path, inode, offset FROM file_offsets").fetchall()
        return {row["path"]: (row["inode"], row["offset"]) for row in rows}

    def known_exceptions(self) -> Set[str]:
        with self._lock:
            return {row[0] for row in self._conn.execute("SELECT exception FROM exceptions")}

    def known_error_templates(self) -> Set[int]:
        with self._lock:
            return {row[0] for row in self._conn.execute("SELECT template_id FROM templates WHERE error_count > 0")}

    def last_alert_time(self, rule: str, key: str) -> Optional[datetime]:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(created_at) FROM alerts WHERE rule = ? AND key = ?", (rule, key)
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def error_count_between(self, start: datetime, end: datetime) -> int:
        placeholders = ", ".join("?" * len(ERROR_LEVELS))
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) FROM records WHERE baseline = 0 AND level IN ({placeholders}) AND event_time >= ? AND event_time < ?",
                (*sorted(ERROR_LEVELS), iso(start), iso(end)),
            ).fetchone()
        return int(row[0])

    def list_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> List[dict]:
        query = "SELECT * FROM alerts" + (" WHERE acknowledged = 0" if unacknowledged_only else "") + " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(query, (limit,)).fetchall()
        return [{**dict(row), "acknowledged": bool(row["acknowledged"])} for row in rows]

    def records_frame(self, limit: int = 50000, since: Optional[datetime] = None, include_raw: bool = False) -> pd.DataFrame:
        """Most recent records (oldest first) joined with their current template text."""
        where, params = "", []
        if since is not None:
            where, params = "WHERE r.event_time >= ?", [iso(since)]
        query = f"""
            SELECT * FROM (
                SELECT r.id, r.timestamp, r.event_time, r.level, r.category, r.channel, r.message, r.exception,
                       r.stack_frames, r.source, r.template_id, t.template{", r.raw" if include_raw else ""}
                FROM records r LEFT JOIN templates t ON t.template_id = r.template_id
                {where} ORDER BY r.id DESC LIMIT ?
            ) ORDER BY id
        """
        with self._lock:
            frame = pd.read_sql_query(query, self._conn, params=[*params, limit])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce", format="ISO8601")
        return frame.set_index("id")

    def raw_for_channel(self, channel: str, limit: int = 100000) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT raw FROM (SELECT id, raw FROM records WHERE channel = ? AND raw IS NOT NULL ORDER BY id DESC LIMIT ?) ORDER BY id",
                (channel, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def record(self, record_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                """SELECT r.*, t.template FROM records r LEFT JOIN templates t ON t.template_id = r.template_id
                   WHERE r.id = ?""", (record_id,)
            ).fetchone()
        return dict(row) if row else None

    def stats(self) -> dict:
        with self._lock:
            records = self._conn.execute("SELECT COUNT(*), MAX(ingested_at) FROM records").fetchone()
            alerts = self._conn.execute("SELECT COUNT(*), SUM(acknowledged = 0) FROM alerts").fetchone()
            templates = self._conn.execute("SELECT COUNT(*) FROM templates").fetchone()
        return {
            "records": int(records[0]),
            "last_ingested_at": records[1],
            "templates": int(templates[0]),
            "alerts": int(alerts[0]),
            "open_alerts": int(alerts[1] or 0),
        }
