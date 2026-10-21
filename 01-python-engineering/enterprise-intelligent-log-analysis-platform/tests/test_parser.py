from datetime import datetime, timezone

import pytest

from app.models.log_model import LogEntry
from app.parsers.log_parser import parse_log_line


def test_level_line():
    entry = parse_log_line("ERROR - Database connection failed", source="app.log")
    assert entry.level == "ERROR"
    assert entry.message == "Database connection failed"
    assert entry.timestamp is None
    assert entry.source == "app.log"


def test_iso_timestamped_line_with_timezone():
    entry = parse_log_line("2024-05-01T10:00:00Z WARN cache miss rate high")
    assert entry.level == "WARN"
    assert entry.timestamp == datetime(2024, 5, 1, 10, 0, tzinfo=timezone.utc)
    assert entry.message == "cache miss rate high"


def test_hadoop_line():
    entry = parse_log_line(
        "081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_38865049064139660 terminating"
    )
    assert entry.level == "INFO"
    assert entry.timestamp == datetime(2008, 11, 9, 20, 36, 15)
    assert entry.message.startswith("dfs.DataNode$PacketResponder")


def test_level_is_case_insensitive_and_normalized():
    assert parse_log_line("warning: disk 91% full").level == "WARNING"


def test_unknown_line_is_preserved():
    entry = parse_log_line("free-form text without a level")
    assert entry.level == "UNKNOWN"
    assert entry.message == "free-form text without a level"


def test_empty_line_is_rejected():
    with pytest.raises(ValueError):
        parse_log_line("   ")


@pytest.mark.parametrize(
    "level, category",
    [("FATAL", "critical"), ("ERR", "error"), ("WARN", "warning"), ("TRACE", "debug"), ("NOTICE", "info"), ("UNKNOWN", "unknown")],
)
def test_category_mapping(level, category):
    assert LogEntry(level=level, message="x").category == category
