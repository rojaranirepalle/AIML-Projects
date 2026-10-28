from fastapi.testclient import TestClient

from app.api import app
from app.knowledge.magento import KNOWN_ISSUES, match_issue, match_issues, summarize_known_issues


def test_known_magento_messages_match_expected_issue():
    cases = {
        "Could not ping search engine: No alive nodes found in your cluster": "search-engine-unavailable",
        "SQLSTATE[40001]: Serialization failure: 1213 Deadlock found when trying to get lock": "db-deadlock",
        "Magento\\Framework\\Exception\\LocalizedException: Area code is not set in /var/www/html/vendor/magento/framework/App/State.php:153": "area-code-not-set",
        "Braintree\\Configuration::merchantId needs to be set (or accessToken needs to be passed to Braintree\\Gateway).": "braintree-not-configured",
        "Memory size allocated for the temporary table is more than 20% of innodb_buffer_pool_size.": "innodb-buffer-pool",
        "server_error GET /checkout/ (HTTP 500)": "http-5xx",
    }
    for text, expected in cases.items():
        assert match_issue(text).id == expected, text


def test_unrelated_text_matches_nothing():
    assert match_issues("Customer 42 placed an order") == []


def test_every_issue_has_cause_and_fix():
    ids = [issue.id for issue in KNOWN_ISSUES]
    assert len(ids) == len(set(ids))
    for issue in KNOWN_ISSUES:
        assert issue.cause and issue.fix and issue.severity in {"info", "low", "medium", "high"}


def test_summarize_groups_counts_by_issue_and_orders_by_severity():
    rows = [
        {"template": "cache_invalidate:", "count": 900},
        {"template": "Could not ping search engine: No alive nodes found in your cluster", "count": 5},
        {"template": "Could not ping search engine: No alive nodes found", "count": 2},
    ]
    summary = summarize_known_issues(rows)
    assert [item["id"] for item in summary] == ["search-engine-unavailable", "debug-logging-noise"]
    assert summary[0]["count"] == 7 and len(summary[0]["examples"]) == 2


def test_knowledge_api():
    client = TestClient(app)
    assert len(client.get("/knowledge").json()["items"]) == len(KNOWN_ISSUES)
    assert client.get("/knowledge/match", params={"text": "Unable to send mail"}).json()["items"][0]["id"] == "mail-send-failed"


def test_summary_tolerates_all_null_exception_column():
    import numpy as np
    import pandas as pd

    from app.analytics.pandas_analytics import generate_summary

    frame = pd.DataFrame({
        "level": ["CRITICAL", "INFO"],
        "message": ["Could not ping search engine: No alive nodes found in your cluster", "ok"],
        "exception": [np.nan, np.nan],  # what SQLite returns when no record has an exception
    })
    assert generate_summary(frame)["known_issues"][0]["id"] == "search-engine-unavailable"
