from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HDFS_LOG = PROJECT_ROOT / "data" / "HDFS_2k.log"


@pytest.fixture
def mixed_log(tmp_path: Path) -> Path:
    """A small log covering every supported format plus an unrecognized line."""
    lines = [
        "INFO - Application started",
        "2024-05-01T10:00:00Z ERROR Database connection failed",
        "2024-05-01 10:05:00 WARNING: Memory usage high",
        "081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_123 terminating",
        "",
        "something the parser does not recognize",
    ]
    path = tmp_path / "mixed.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def timestamped_log(tmp_path: Path) -> Path:
    """Three hours of hourly HDFS-style records with one rare critical event."""
    lines = []
    for hour in range(3):
        for minute in range(0, 60, 5):
            lines.append(
                f"081109 {hour:02d}{minute:02d}00 1 INFO dfs.DataNode: Received block blk_{hour}{minute} of size 6710 from /10.0.0.{minute}"
            )
    lines.append("081109 025900 1 FATAL dfs.FSNamesystem: Disk failure on node 10.0.0.9")
    path = tmp_path / "timestamped.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def hdfs_log() -> Path:
    if not HDFS_LOG.is_file():
        pytest.skip("data/HDFS_2k.log is not available")
    return HDFS_LOG
