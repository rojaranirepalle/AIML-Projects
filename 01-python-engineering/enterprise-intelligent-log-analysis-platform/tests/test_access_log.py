from app.analytics.access_analytics import analyze_access, mask_ip, records_from_raw
from app.parsers.access_log import area_for, normalize_path, parse_access_line
from app.parsers.log_parser import parse_log_line
from app.services.log_service import process_log_file

LINES = [
    '198.51.100.7 - - [03/Oct/2026:14:05:11 +0000] "GET /catalogsearch/result/?q=bag HTTP/1.1" 500 1234 "-" "Mozilla/5.0" 2.812',
    '198.51.100.8 - - [03/Oct/2026:14:05:12 +0000] "POST /rest/default/V1/carts/mine/payment-information HTTP/1.1" 200 88 "-" "Mozilla/5.0" 1.200',
    '66.249.66.1 - - [03/Oct/2026:14:05:13 +0000] "GET /static/version1727740800/frontend/Magento/luma/en_US/jquery.js HTTP/1.1" 200 5000 "-" "Googlebot/2.1" 0.004',
    '198.51.100.9 - - [03/Oct/2026:14:06:01 +0000] "GET /gear/bags.html HTTP/1.1" 404 10 "-" "Mozilla/5.0" 0.300',
    '198.51.100.9 - - [03/Oct/2026:14:07:01 +0000] "GET /catalog/product/view/id/1234 HTTP/1.1" 200 10 "-" "Mozilla/5.0"',
]


def test_parse_combined_line_with_request_time():
    record = parse_access_line(LINES[0])
    assert (record.method, record.route, record.status, record.area) == ("GET", "/catalogsearch/result/", 500, "Search")
    assert record.response_time == 2.812 and record.timestamp.isoformat() == "2026-10-03T14:05:11+00:00"
    assert parse_access_line(LINES[4]).response_time is None  # request time is optional
    assert parse_access_line("not an access line") is None


def test_routes_and_areas():
    assert normalize_path("/catalog/product/view/id/1234?x=1") == "/catalog/product/view/id/<ID>"
    assert normalize_path("/rest/default/V1/guest-carts/9f86d081884c7d659a2feaa0c55ad015/items") == "/rest/default/V1/guest-carts/<ID>/items"
    assert normalize_path("/static/version1727740800/frontend/a.js") == "/static/…"
    assert area_for("/rest/default/V1/carts/mine/payment-information") == "Checkout"
    assert area_for("/rest/default/V1/products") == "REST API"
    assert area_for("/checkout/cart/") == "Cart"
    assert area_for("/women.html") == "Storefront pages"


def test_access_lines_join_the_shared_pipeline():
    entry = parse_log_line(LINES[0], source="access.log")
    assert (entry.level, entry.channel) == ("ERROR", "nginx")
    assert entry.message == "server_error GET /catalogsearch/result/ (HTTP 500)"
    assert parse_log_line(LINES[3]).level == "WARNING"


def test_traffic_analytics():
    result = analyze_access(records_from_raw(LINES))
    assert result["requests"] == 5
    assert result["status_classes"] == {"2xx": 3, "4xx": 1, "5xx": 1}
    assert result["error_rate_5xx"] == 0.2 and result["bot_share"] == 0.2
    assert result["latency"]["available"] and result["latency"]["p50"] == 0.75  # median of 0.004, 0.3, 1.2, 2.812
    assert result["top_5xx_routes"][0]["route"] == "/catalogsearch/result/"
    assert all(client["client"].endswith(".x") for client in result["top_clients"])
    assert analyze_access([])["available"] is False


def test_mask_ip():
    assert mask_ip("203.0.113.42") == "203.0.113.x"
    assert mask_ip("2001:db8:85a3::8a2e:370:7334").endswith(":…")


def test_directory_with_access_log(tmp_path):
    (tmp_path / "access.log").write_text("\n".join(LINES) + "\n")
    (tmp_path / "system.log").write_text("[2026-10-03T14:05:10+00:00] main.CRITICAL: Could not ping search engine: No alive nodes found in your cluster [] []\n")
    summary = process_log_file(tmp_path)["summary"]
    assert summary["access"]["available"] and summary["access"]["requests"] == 5
    assert {issue["id"] for issue in summary["known_issues"]} >= {"search-engine-unavailable", "http-5xx"}
