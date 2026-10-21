import json

import pandas as pd
import pytest

from app.services.log_service import process_log_file


def test_process_mixed_formats_and_write_reports(mixed_log, tmp_path):
    csv_path, json_path = tmp_path / "out" / "records.csv", tmp_path / "out" / "summary.json"
    result = process_log_file(mixed_log, csv_path, json_path)

    summary = result["summary"]
    assert summary["total_logs"] == 5  # the blank line is ignored, not counted
    assert summary["skipped_lines"] == 0
    assert summary["severity_distribution"]["UNKNOWN"] == 1

    records = pd.read_csv(csv_path)
    assert {"timestamp", "level", "category", "message", "template_id", "template"} <= set(records.columns)
    assert json.loads(json_path.read_text())["total_logs"] == 5


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_log_file(tmp_path / "missing.log")


def test_hdfs_sample_end_to_end(hdfs_log):
    summary = process_log_file(hdfs_log)["summary"]
    assert summary["total_logs"] == 2000
    assert summary["severity_distribution"] == {"INFO": 1920, "WARN": 80}
    assert summary["template_count"] < 30
    assert summary["ml_anomalies"]["available"] is True
    assert summary["forecast"]["available"] is True
