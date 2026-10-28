"""Nginx/Apache access logs in the combined format, with Magento-aware URL grouping.

    203.0.113.7 - - [03/Oct/2026:14:05:11 +0000] "GET /catalogsearch/result/?q=bag HTTP/1.1" 500 1234 "-" "Mozilla/5.0" 0.812

An optional trailing request time (seconds, ``$request_time`` or ``rt=0.123``)
is used for latency statistics when present.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

ACCESS_LINE = re.compile(
    r'^(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<time>\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\] '
    r'"(?:(?P<method>[A-Z]+) (?P<path>\S+)(?: (?P<protocol>[^"]*))?|[^"]*)" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-)'
    r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?'
    r'(?:.*?\s(?:rt=|request_time=)?(?P<rt>\d+\.\d+))?\s*$'
)

_ID_SEGMENT = re.compile(r"^(?:\d+|[0-9a-fA-F]{16,}|[0-9a-fA-F-]{36}|[A-Za-z0-9]{32})$")
_STATIC_VERSION = re.compile(r"^/(static|media)/(?:version\d+/)?")
BOT_AGENT = re.compile(r"bot|crawl|spider|slurp|bingpreview|facebookexternalhit|curl|wget|python-requests|httpclient|headless", re.I)

# First match wins: specific checkout/API paths before the generic REST bucket.
AREAS = [
    ("Checkout", re.compile(r"^/(checkout(?!/cart)|rest/[^/]+/V1/(carts|guest-carts)/[^/]+/(payment-information|shipping-information|totals-information))", re.I)),
    ("Cart", re.compile(r"^/(checkout/cart|rest/[^/]+/V1/(carts|guest-carts))", re.I)),
    ("GraphQL", re.compile(r"^/graphql", re.I)),
    ("REST API", re.compile(r"^/rest/", re.I)),
    ("Admin", re.compile(r"^/(admin|backend)\b", re.I)),
    ("Search", re.compile(r"^/(catalogsearch|search)\b", re.I)),
    ("Customer", re.compile(r"^/customer/", re.I)),
    ("Static & media", re.compile(r"^/(static|media|pub)/", re.I)),
    ("Health", re.compile(r"^/(health_check\.php|robots\.txt|favicon\.ico)", re.I)),
]


@dataclass
class AccessRecord:
    timestamp: datetime
    ip: str
    method: Optional[str]
    path: str
    route: str
    area: str
    status: int
    bytes: int
    agent: str
    is_bot: bool
    response_time: Optional[float]


def normalize_path(path: str) -> str:
    """Drop query strings and replace IDs/hashes with ``<ID>`` so URLs group by route."""
    path = path.split("?", 1)[0].split("#", 1)[0] or "/"
    match = _STATIC_VERSION.match(path)
    if match:
        return f"/{match.group(1)}/…"
    segments = ["<ID>" if _ID_SEGMENT.match(segment) else segment for segment in path.split("/")]
    route = "/".join(segments)
    return route if len(route) <= 120 else route[:119] + "…"


def area_for(path: str) -> str:
    for name, pattern in AREAS:
        if pattern.search(path):
            return name
    return "Storefront pages"


def parse_access_line(line: str) -> Optional[AccessRecord]:
    match = ACCESS_LINE.match(line.strip())
    if not match:
        return None
    path = match.group("path") or "-"
    agent = match.group("agent") or ""
    rt = match.group("rt")
    return AccessRecord(
        timestamp=datetime.strptime(match.group("time"), "%d/%b/%Y:%H:%M:%S %z"),
        ip=match.group("ip"),
        method=match.group("method"),
        path=path,
        route=normalize_path(path) if path != "-" else "-",
        area=area_for(path),
        status=int(match.group("status")),
        bytes=0 if match.group("bytes") == "-" else int(match.group("bytes")),
        agent=agent,
        is_bot=bool(BOT_AGENT.search(agent)),
        response_time=float(rt) if rt else None,
    )


def level_for_status(status: int) -> str:
    if status >= 500:
        return "ERROR"
    if status >= 400:
        return "WARNING"
    return "INFO"


STATUS_LABELS = {5: "server_error", 4: "client_error", 3: "redirect", 2: "ok", 1: "informational"}


def access_message(record: AccessRecord) -> str:
    """Message for the shared pipeline, e.g. ``server_error GET /checkout/ (HTTP 500)``.

    The status class leads as a word because template mining masks numbers and
    routes on the first tokens: 5xx responses therefore never merge with 2xx ones.
    """
    label = STATUS_LABELS.get(record.status // 100, "unknown")
    return f"{label} {record.method or '-'} {record.route} (HTTP {record.status})"
