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
    assert "raw" not in records.columns  # stack traces stay out of the flat CSV
    assert json.loads(json_path.read_text())["total_logs"] == 5


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_log_file(tmp_path / "missing.log")


def test_adobe_commerce_sample_end_to_end(magento_sample):
    summary = process_log_file(magento_sample.parent)["summary"]  # system log + nginx access log
    assert summary["access"]["available"] and summary["access"]["error_rate_5xx"] > 0
    assert summary["known_issues"][0]["id"] == "search-engine-unavailable"
    assert summary["skipped_lines"] == 0
    assert "UNKNOWN" not in summary["severity_distribution"]  # stack-trace lines are folded into records
    assert summary["template_count"] < 40
    assert "OpenSearch\\Common\\Exceptions\\NoNodesAvailableException" in summary["top_exceptions"]
    ml = summary["ml_anomalies"]
    assert ml["available"] is True
    rare = " ".join(item["template"] for item in ml["anomalous_templates"][:5])
    assert "Disk usage" in rare and "Undefined array key" in rare
    assert summary["forecast"]["available"] is True
