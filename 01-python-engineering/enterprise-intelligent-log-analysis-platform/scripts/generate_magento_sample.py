"""Generate a synthetic Adobe Commerce (Magento 2) var/log/system.log sample.

Every store, customer, email and order value is invented (example.com
domains, a fictional "Acme" vendor), so the file is safe to commit. Real
store logs belong in data/ — which is git-ignored — never in samples/.

The sample covers three days of normal traffic with a daily rhythm, plus:
* checkout-peak database deadlocks with multi-line stack traces,
* a 45-minute search-engine outage on the last day (the "incident"), and
* a handful of rare events for the anomaly model to find.

It also writes a matching Nginx access log (combined format plus request
time) for the same three days, where the outage shows up as 5xx responses on
search and category pages and slow checkout calls during deadlock peaks.

Usage:  python scripts/generate_magento_sample.py [--output PATH] [--access-output PATH] [--seed N]
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "samples" / "adobe_commerce_system.log"
DEFAULT_ACCESS_OUTPUT = DEFAULT_OUTPUT.with_name("nginx_access.log")
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = 3
INCIDENT_START = START + timedelta(days=2, hours=14)
INCIDENT_END = INCIDENT_START + timedelta(minutes=45)

CRON_JOBS = [
    "indexer_reindex_all_invalid", "sales_grid_order_async_insert", "catalog_product_alert",
    "newsletter_send_all", "consumers_runner", "captcha_delete_expired_images",
    "catalog_index_refresh_price", "sales_clean_quotes",
]
CONSUMERS = ["async.operations.all", "product_action_attribute.update", "exportProcessor", "inventory.reservations.update"]
FIRST_NAMES = ["asha", "ravi", "meera", "john", "li", "sara", "omar", "nina"]


def ts(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"


def line(moment: datetime, level: str, message: str, context: str = "[]", channel: str = "main") -> str:
    return f"[{ts(moment)}] {channel}.{level}: {message} {context} []"


def exception_context(cls: str, code: int, message: str, at: str, frames: list, previous: str = "") -> str:
    parts = [f'{{"exception":"[object] ({cls}(code: {code}): {message} at {at})']
    if previous:
        parts.append(f"[previous exception] [object] ({previous})")
    parts.append("[stacktrace]")
    parts += [f"#{i} {frame}" for i, frame in enumerate(frames)]
    parts.append(f'#{len(frames)} {{main}}"}}')
    return "\n".join(parts)


def deadlock(moment: datetime, rng: random.Random) -> str:
    order = rng.randint(4000, 9999)
    message = "SQLSTATE[40001]: Serialization failure: 1213 Deadlock found when trying to get lock; try restarting transaction"
    context = exception_context(
        "Zend_Db_Statement_Exception", 40001, message,
        "/var/www/html/vendor/magento/zend-db/library/Zend/Db/Statement/Pdo.php:234",
        [
            "/var/www/html/vendor/magento/framework/DB/Statement/Pdo/Mysql.php(91): Zend_Db_Statement_Pdo->_execute(Array)",
            "/var/www/html/vendor/magento/framework/DB/Adapter/Pdo/Mysql.php(588): Magento\\\\Framework\\\\DB\\\\Statement\\\\Pdo\\\\Mysql->execute(Array)",
            f"/var/www/html/vendor/magento/module-inventory-reservations/Model/ResourceModel/SaveMultiple.php(63): order {order}",
            "/var/www/html/vendor/magento/module-quote/Model/QuoteManagement.php(611): Magento\\\\Quote\\\\Model\\\\QuoteManagement->submitQuote()",
        ],
        previous="PDOException(code: 40001): SQLSTATE[40001]: Serialization failure at /var/www/html/vendor/magento/zend-db/library/Zend/Db/Statement/Pdo.php:228",
    )
    return line(moment, "CRITICAL", message, context)


def search_outage(moment: datetime, rng: random.Random) -> list:
    context = exception_context(
        "OpenSearch\\\\Common\\\\Exceptions\\\\NoNodesAvailableException", 0,
        "No alive nodes found in your cluster",
        "/var/www/html/vendor/opensearch-project/opensearch-php/src/OpenSearch/ConnectionPool/StaticNoPingConnectionPool.php:64",
        [
            "/var/www/html/vendor/opensearch-project/opensearch-php/src/OpenSearch/Transport.php(106): OpenSearch\\\\ConnectionPool\\\\StaticNoPingConnectionPool->nextConnection()",
            "/var/www/html/vendor/magento/module-open-search/Model/OpenSearch.php(212): OpenSearch\\\\Client->ping()",
        ],
    )
    records = [line(moment, "CRITICAL", "Could not ping search engine: No alive nodes found in your cluster", context)]
    if rng.random() < 0.6:
        records.append(line(moment + timedelta(milliseconds=40), "ERROR",
                            "Catalog search request failed: search engine unavailable, returning empty result"))
    return records


def normal_event(moment: datetime, rng: random.Random, peak: bool) -> list:
    roll = rng.random()
    if roll < 0.30:
        job = rng.choice(CRON_JOBS)
        stats = json.dumps({"sum": round(rng.uniform(0.01, 4.5), 2), "count": 1, "realmem": "2 MB", "realmem_start": "112 MB"})
        return [line(moment, "INFO", f"Cron Job {job} is run"),
                line(moment + timedelta(seconds=rng.randint(1, 20)), "INFO", f"Cron Job {job} is successfully finished. Statistics:", stats)]
    if roll < 0.52:
        product = rng.randint(100, 2400)
        context = json.dumps({"method": "POST", "url": f"https://shop.example.com/rest/default/V1/products/{product}",
                              "invalidateInfo": {"tags": [f"cat_p_{product}"], "mode": "matchingAnyTag"}, "is_exception": False})
        return [line(moment, "DEBUG", "cache_invalidate:", context)]
    if roll < 0.64:
        return [line(moment, "INFO", f'Consumer "{rng.choice(CONSUMERS)}" skipped as required connection "amqp" is not configured. Unknown connection name amqp')]
    if roll < 0.72:
        return [line(moment, "INFO", "Broken reference: the 'catalog.compare.sidebar' tried to reorder itself towards 'cart_sidebar', but their parents are different: 'sidebar.additional' and 'sidebar.main' respectively.")]
    if roll < 0.78:
        return [line(moment, "WARNING", f"Session size of {rng.randint(260000, 900000)} exceeded allowed session max size of 256000.")]
    if roll < 0.84:
        email = f"{rng.choice(FIRST_NAMES)}.{rng.randint(10, 99)}@example.com"
        ip = f"203.0.113.{rng.randint(1, 254)}"
        return [line(moment, "WARNING", f"Failed login attempt for customer {email} from {ip}")]
    if roll < 0.89:
        return [line(moment, "ERROR", f'Item (Magento\\Catalog\\Model\\Product\\Interceptor) with the same ID "{rng.randint(100, 2400)}" already exists.')]
    if roll < 0.93:
        quote = "%032x" % rng.getrandbits(128)
        return [line(moment, "ERROR", f"Payment gateway request failed for quote {quote}: Transaction declined (code {rng.choice([2001, 2004, 2046])})")]
    if roll < 0.955:
        context = exception_context(
            "Magento\\\\Framework\\\\Exception\\\\MailException", 0, "Unable to send mail. Please try again later.",
            "/var/www/html/vendor/magento/module-email/Model/Transport.php:157",
            ["/var/www/html/vendor/magento/module-sales/Model/Order/Email/SenderBuilder.php(88): Magento\\\\Email\\\\Model\\\\Transport->sendMessage()"],
        )
        return [line(moment, "ERROR", "Unable to send mail. Please try again later.", context)]
    if roll < 0.975:
        return [line(moment, "ERROR", "Invalid template file: 'Acme_Theme::product/view/badge.phtml' in module: 'Acme_Theme' block's name: 'product.badge'")]
    if peak or roll < 0.985:
        return [deadlock(moment, rng)]
    return [line(moment, "NOTICE", "Indexer 'catalogsearch_fulltext' was invalidated by a mass product update")]


def rare_events() -> list:
    """Events that happen once or twice: what an anomaly detector should surface."""
    day1, day2 = START + timedelta(hours=3, minutes=12), START + timedelta(days=1, hours=22, minutes=5)
    undefined_key = exception_context(
        "Exception", 0, 'Warning: Undefined array key "sku" in /var/www/html/app/code/Acme/ProductImport/Model/Import.php on line 87',
        "/var/www/html/vendor/magento/framework/App/ErrorHandler.php:62",
        ["/var/www/html/app/code/Acme/ProductImport/Model/Import.php(87): Magento\\\\Framework\\\\App\\\\ErrorHandler->handler()",
         "/var/www/html/app/code/Acme/ProductImport/Cron/RunImport.php(41): Acme\\\\ProductImport\\\\Model\\\\Import->execute()"],
    )
    return [
        line(day1, "CRITICAL", 'Exception: Warning: Undefined array key "sku" in /var/www/html/app/code/Acme/ProductImport/Model/Import.php on line 87', undefined_key),
        line(day1 + timedelta(minutes=30), "CRITICAL", 'Exception: Warning: Undefined array key "sku" in /var/www/html/app/code/Acme/ProductImport/Model/Import.php on line 87', undefined_key),
        line(day2, "ALERT", "Disk usage at 96% on /var/www/html/var; log rotation required"),
        line(day2 + timedelta(minutes=7), "CRITICAL", "Report ID: webapi-6f3c2a9e1b7d4; Message: Area code is not set",
             exception_context("Magento\\\\Framework\\\\Exception\\\\LocalizedException", 0, "Area code is not set",
                               "/var/www/html/vendor/magento/framework/App/State.php:153",
                               ["/var/www/html/vendor/magento/framework/App/Area.php(126): Magento\\\\Framework\\\\App\\\\State->getAreaCode()"])),
    ]


def generate(seed: int = 7) -> list:
    rng = random.Random(seed)
    records = []
    moment = START
    end = START + timedelta(days=DAYS)
    while moment < end:
        hour = moment.hour
        # Daily rhythm: quiet overnight, busy 09:00-21:00 UTC, checkout peak 13:00-15:00.
        rate = 0.35 if hour < 6 else 1.0 if hour < 9 or hour > 21 else 1.8
        peak = 13 <= hour < 15
        if INCIDENT_START <= moment < INCIDENT_END:
            for _ in range(rng.randint(2, 5)):
                records.append((moment, search_outage(moment + timedelta(seconds=rng.uniform(0, 59)), rng)))
        if rng.random() < rate:
            event_time = moment + timedelta(seconds=rng.uniform(0, 59), microseconds=rng.randint(0, 999999))
            records.append((event_time, normal_event(event_time, rng, peak and rng.random() < 0.08)))
        moment += timedelta(minutes=1)
    records += [(record_time(text), [text]) for text in rare_events()]
    records.sort(key=lambda item: item[0])
    return [text for _, group in records for text in group]


ROUTES = [
    # (weight, method, path template, area-specific base latency in seconds)
    (30, "GET", "/static/version1727740800/frontend/Magento/luma/en_US/{asset}", 0.004),
    (12, "GET", "/media/catalog/product/cache/{hash}/{letter}/{letter}/{sku}.jpg", 0.006),
    (14, "GET", "/{category}.html", 0.35),
    (12, "GET", "/{product}.html", 0.42),
    (5, "GET", "/catalogsearch/result/?q={term}", 0.55),
    (6, "POST", "/customer/section/load/?sections=cart%2Cmessages&update_section_id=true", 0.12),
    (4, "GET", "/checkout/cart/", 0.48),
    (3, "POST", "/rest/default/V1/guest-carts/{hash}/estimate-shipping-methods", 0.30),
    (2, "GET", "/checkout/", 0.62),
    (1.2, "POST", "/rest/default/V1/carts/mine/payment-information", 0.95),
    (2, "POST", "/graphql", 0.25),
    (1.5, "GET", "/customer/account/login/", 0.30),
    (0.6, "GET", "/admin/sales/order/index/key/{hash}/", 0.70),
    (1, "GET", "/robots.txt", 0.002),
]
ASSETS = ["requirejs/require.js", "css/styles-m.css", "mage/requirejs/mixins.js", "jquery.js", "images/logo.svg"]
CATEGORIES = ["women/tops-women", "men/bottoms-men", "gear/bags", "gear/fitness-equipment", "sale", "what-is-new"]
PRODUCTS = ["joust-duffle-bag", "strive-shoulder-pack", "push-it-messenger-bag", "radiant-tee", "breathe-easy-tank", "argus-all-weather-tank"]
TERMS = ["bag", "yoga", "tank", "jacket", "shorts"]
BROWSERS = [
    "Mozilla/5.0 (Macintosh) Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0) Chrome/129.0",
    "Mozilla/5.0 (iPhone) Mobile/15E148",
    "Mozilla/5.0 (Linux; Android 14) Chrome/129.0",
]
BOTS = ["Mozilla/5.0 (compatible; Googlebot/2.1)", "Mozilla/5.0 (compatible; bingbot/2.0)", "python-requests/2.32"]


def access_line(moment: datetime, rng: random.Random, outage: bool, peak: bool) -> str:
    routes = ROUTES
    if outage and rng.random() < 0.5:  # shoppers retry search and category pages during the outage
        routes = [route for route in ROUTES if route[2].startswith("/catalogsearch") or route[2] == "/{category}.html"]
    pick = rng.uniform(0, sum(route[0] for route in routes))
    for weight, method, template, base in routes:
        pick -= weight
        if pick <= 0:
            break
    path = template.format(
        asset=rng.choice(ASSETS), hash="%032x" % rng.getrandbits(128), letter=rng.choice("abcdefghjkmnpr"),
        sku=f"mb0{rng.randint(1, 9)}-{rng.choice(['black', 'blue', 'gray'])}-0", category=rng.choice(CATEGORIES),
        product=rng.choice(PRODUCTS), term=rng.choice(TERMS),
    )
    status, latency = 200, base * rng.lognormvariate(0, 0.45)
    if method == "POST" and "/rest/" in path and rng.random() < 0.05:
        status = 400
    if template.endswith(".html") and rng.random() < 0.02:
        status = 404
    if template.startswith("/checkout/") and rng.random() < 0.15:
        status = 302
    if outage and (template.startswith("/catalogsearch") or template == "/{category}.html"):
        status, latency = (503 if rng.random() < 0.3 else 500), rng.uniform(1.5, 6.0)
    if peak and "payment-information" in path:
        latency *= rng.uniform(2.5, 6.0)
        if rng.random() < 0.12:
            status = 500
    size = 0 if status in (302, 304) else rng.randint(200, 90000)
    bot = rng.random() < 0.12
    agent = rng.choice(BOTS) if bot else rng.choice(BROWSERS)
    ip = f"198.51.100.{rng.randint(1, 254)}" if not bot else f"66.249.66.{rng.randint(1, 30)}"
    referer = "-" if bot else "https://shop.example.com/"
    stamp = moment.strftime("%d/%b/%Y:%H:%M:%S +0000")
    return f'{ip} - - [{stamp}] "{method} {path} HTTP/1.1" {status} {size} "{referer}" "{agent}" {latency:.3f}'


def generate_access(seed: int = 7) -> list:
    rng = random.Random(seed + 1000)
    lines = []
    moment, end = START, START + timedelta(days=DAYS)
    while moment < end:
        hour = moment.hour
        rate = 0.3 if hour < 6 else 1.0 if hour < 9 or hour > 21 else 2.2
        peak = 13 <= hour < 15
        outage = INCIDENT_START <= moment < INCIDENT_END
        count = int(rate) + (1 if rng.random() < rate - int(rate) else 0)
        for _ in range(count):
            lines.append((moment + timedelta(seconds=rng.uniform(0, 59)), outage, peak))
        moment += timedelta(minutes=1)
    lines.sort(key=lambda item: item[0])
    return [access_line(when, rng, outage, peak) for when, outage, peak in lines]


def record_time(text: str) -> datetime:
    return datetime.fromisoformat(text[1:text.index("]")])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--access-output", type=Path, default=DEFAULT_ACCESS_OUTPUT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    lines = generate(args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} records to {args.output}")
    access = generate_access(args.seed)
    args.access_output.parent.mkdir(parents=True, exist_ok=True)
    args.access_output.write_text("\n".join(access) + "\n", encoding="utf-8")
    print(f"Wrote {len(access)} requests to {args.access_output}")


if __name__ == "__main__":
    main()
