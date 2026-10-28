from datetime import datetime, timezone

from app.models.log_model import LogEntry
from app.parsers.log_parser import iter_records, parse_log_line

DEADLOCK = r'''[2026-10-01T09:15:02.123456+00:00] main.CRITICAL: SQLSTATE[40001]: Serialization failure: 1213 Deadlock found {"exception":"[object] (Zend_Db_Statement_Exception(code: 40001): SQLSTATE[40001] at /var/www/html/vendor/Pdo.php:234)
[previous exception] [object] (PDOException(code: 40001): SQLSTATE[40001] at /var/www/html/vendor/Pdo.php:228)
[stacktrace]
#0 /var/www/html/vendor/magento/framework/DB/Statement/Pdo/Mysql.php(91): Zend_Db_Statement_Pdo->_execute(Array)
#1 /var/www/html/vendor/magento/module-quote/Model/QuoteManagement.php(611): submitQuote()
#2 {main}"} []'''


def test_simple_monolog_record():
    entry = parse_log_line('[2026-10-01T09:15:04.000000+00:00] main.ERROR: Item (Magento\\Catalog\\Model\\Product\\Interceptor) with the same ID "1234" already exists. [] []')
    assert entry.level == "ERROR"
    assert entry.channel == "main"
    assert entry.timestamp == datetime(2026, 10, 1, 9, 15, 4, tzinfo=timezone.utc)
    assert entry.message.endswith('already exists.')  # trailing "[] []" removed
    assert entry.exception is None


def test_context_json_is_not_part_of_message():
    entry = parse_log_line('[2026-10-01T09:15:03.000000+00:00] main.INFO: Cron Job sales_clean_quotes is successfully finished. Statistics: {"sum":0.05,"count":1} []')
    assert entry.message == "Cron Job sales_clean_quotes is successfully finished. Statistics:"


def test_stack_trace_is_one_record_with_exception_class():
    lines = (DEADLOCK + "\n[2026-10-01T09:15:03.000000+00:00] main.INFO: next record [] []\n").splitlines()
    records = list(iter_records(lines))
    assert [number for number, _ in records] == [1, 7]

    entry = parse_log_line(records[0][1])
    assert entry.level == "CRITICAL"
    assert entry.exception == "Zend_Db_Statement_Exception"
    assert entry.stack_frames == 3
    assert entry.message == "SQLSTATE[40001]: Serialization failure: 1213 Deadlock found"


def test_php_exception_prefix_is_detected():
    entry = parse_log_line('[2026-10-01T09:15:05.000000+00:00] main.CRITICAL: Exception: Warning: Undefined array key "sku" in /var/www/html/app/code/Acme/Import.php on line 87 [] []')
    assert entry.exception == "Exception"


def test_namespaced_exception_class_is_unescaped():
    entry = parse_log_line('[2026-10-01T09:15:05+00:00] main.ERROR: Unable to send mail. {"exception":"[object] (Magento\\\\Framework\\\\Exception\\\\MailException(code: 0): Unable at /x.php:1)"} []')
    assert entry.exception == "Magento\\Framework\\Exception\\MailException"


def test_alert_and_emergency_are_critical():
    assert parse_log_line("[2026-10-01T00:00:00+00:00] main.ALERT: Disk usage at 96% [] []").category == "critical"
    assert LogEntry(level="EMERGENCY", message="x").category == "critical"


def test_non_monolog_lines_are_not_merged():
    records = list(iter_records(["INFO - started", "free text", "ERROR - failed"]))
    assert [text for _, text in records] == ["INFO - started", "free text", "ERROR - failed"]


def test_json_message_is_flattened_without_volatile_keys():
    entry = parse_log_line(
        '[2026-06-22T18:55:40.812643+00:00] main.INFO: {"feed":"salesOrders","operation":"full reindex(legacy)",'
        '"status":"Initialize","elapsed":"00:00:00 163 ms","pid":"52","caller":"bin\\/magento setup:install --db-password=magento"} [] []'
    )
    assert entry.message == "feed=salesOrders operation=full reindex(legacy) status=Initialize"


def test_credentials_are_masked():
    from app.parsers.template_miner import mask_text
    assert mask_text("bin/magento setup:install --db-password=magento --db-name=x") == "bin/magento setup:install <SECRET> --db-name=x"
