"""Known Adobe Commerce (Magento 2) log events: likely cause, fix steps and commands.

Each entry is matched with a regular expression against a record's message,
exception class or template. The list is deliberately conservative: it states
the usual cause and the first checks to make, not a guaranteed root cause.
Commands assume shell access to the Magento root (in docker-magento, prefix
them with ``bin/`` from the project folder, e.g. ``bin/magento``).
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class KnownIssue:
    id: str
    title: str
    pattern: str
    area: str
    severity: str  # info | low | medium | high
    cause: str
    fix: List[str]
    commands: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("pattern")
        return data


KNOWN_ISSUES: List[KnownIssue] = [
    KnownIssue(
        id="search-engine-unavailable",
        title="Search engine unreachable",
        pattern=r"No alive nodes found|Could not ping search engine|NoNodesAvailableException|Could not validate a connection to (Elasticsearch|OpenSearch)",
        area="Catalog search",
        severity="high",
        cause="Magento cannot reach OpenSearch/Elasticsearch: the service is down, out of memory, or the host/port in the search configuration is wrong. Catalog search, layered navigation and category pages fail while it lasts.",
        fix=[
            "Check that the search container/service is running and healthy.",
            "Confirm the configured engine, host and port match the running service.",
            "When it is back, reindex catalog search so results are complete.",
        ],
        commands=[
            "docker compose ps opensearch",
            "bin/magento config:show catalog/search/engine",
            "bin/magento config:show catalog/search/opensearch_server_hostname",
            "bin/magento indexer:reindex catalogsearch_fulltext",
        ],
    ),
    KnownIssue(
        id="db-deadlock",
        title="Database deadlock",
        pattern=r"SQLSTATE\[40001\]|1213 Deadlock found|Serialization failure",
        area="Database",
        severity="high",
        cause="Two transactions locked the same rows in opposite order, so MySQL/MariaDB aborted one. Common during checkout peaks, inventory reservations, or when full reindexes and cron jobs run alongside storefront traffic.",
        fix=[
            "Set indexers to 'Update by Schedule' so saves do not reindex synchronously.",
            "Avoid running full reindexes or heavy imports during peak traffic.",
            "Inspect the latest deadlock to see which tables and queries collide.",
            "If one custom module appears in every stack trace, review its transactions.",
        ],
        commands=[
            "bin/magento indexer:status",
            "bin/magento indexer:set-mode schedule",
            "mysql -e 'SHOW ENGINE INNODB STATUS\\G'",
        ],
    ),
    KnownIssue(
        id="db-lock-wait-timeout",
        title="Database lock wait timeout",
        pattern=r"1205 Lock wait timeout|Lock wait timeout exceeded",
        area="Database",
        severity="high",
        cause="A query waited longer than innodb_lock_wait_timeout for a row lock held by a long-running transaction (often a reindex, import or stuck cron job).",
        fix=[
            "Find the long-running transaction holding the lock and the process behind it.",
            "Move heavy reindex/import jobs out of peak hours; use 'Update by Schedule' indexers.",
        ],
        commands=["mysql -e 'SHOW FULL PROCESSLIST'", "bin/magento cron:run --group index"],
    ),
    KnownIssue(
        id="area-code-not-set",
        title="Area code is not set",
        pattern=r"Area code is not set",
        area="Code / CLI",
        severity="medium",
        cause="Code that needs an application area (frontend, adminhtml, crontab…) ran before one was set — typically a custom console command, cron job, setup patch or plugin constructor during setup:install / setup:upgrade.",
        fix=[
            "Use the stack trace to find the first non-vendor frame (app/code or a third-party module).",
            "In that command or cron, call Magento\\Framework\\App\\State::setAreaCode() or wrap the work in emulateAreaCode().",
            "Avoid area-dependent work in constructors; move it into execute().",
        ],
        commands=["bin/magento setup:upgrade", "bin/magento cron:run"],
    ),
    KnownIssue(
        id="media-asset-missing",
        title="Media gallery asset missing",
        pattern=r"There is no such media asset with path|error occurred during get media asset list",
        area="Media gallery",
        severity="low",
        cause="The media gallery database references image files that are not in pub/media — usually after installing sample data, copying a database without its media, or deleting files by hand.",
        fix=[
            "Copy the missing files into pub/media, or remove the stale references.",
            "Resynchronise the media gallery with the files on disk.",
        ],
        commands=["bin/magento media-gallery:sync"],
    ),
    KnownIssue(
        id="innodb-buffer-pool",
        title="InnoDB buffer pool too small",
        pattern=r"innodb_buffer_pool_size",
        area="Database",
        severity="medium",
        cause="Magento's temporary tables (used by indexers) need more memory than the database's innodb_buffer_pool_size allows, which slows indexing and can fail it.",
        fix=[
            "Increase innodb_buffer_pool_size in the MySQL/MariaDB configuration (for docker, the db service's config or command).",
            "Restart the database and re-run the affected indexer.",
        ],
        commands=["mysql -e \"SHOW VARIABLES LIKE 'innodb_buffer_pool_size'\"", "bin/magento indexer:reindex"],
    ),
    KnownIssue(
        id="braintree-not-configured",
        title="Braintree enabled without credentials",
        pattern=r"Braintree.*merchantId needs to be set|accessToken needs to be passed to Braintree",
        area="Payments",
        severity="medium",
        cause="The Braintree payment module is active but has no merchant ID / API keys, so every request that touches it logs an error.",
        fix=[
            "Add sandbox or production credentials under Stores > Configuration > Sales > Payment Methods > Braintree,",
            "or disable the Braintree payment method if the store does not use it.",
        ],
        commands=["bin/magento config:show payment/braintree/active", "bin/magento config:set payment/braintree/active 0", "bin/magento cache:flush config"],
    ),
    KnownIssue(
        id="cron-not-installed",
        title="Cron not installed",
        pattern=r"crontab -l|cron(tab)? (is )?not (installed|running)",
        area="Cron",
        severity="medium",
        cause="Magento tried to read the system crontab but none exists, so scheduled jobs (indexers, emails, cleanup) are not running.",
        fix=[
            "Install Magento's crontab for the web-server user.",
            "In docker-magento, start cron from the project folder.",
        ],
        commands=["bin/magento cron:install", "bin/cron start", "bin/magento cron:run"],
    ),
    KnownIssue(
        id="maintenance-mode",
        title="Maintenance mode is enabled",
        pattern=r"maintenance mode is enabled",
        area="Deployment",
        severity="low",
        cause="A request or command ran while the store was in maintenance mode — expected during a deployment, a problem if the flag was left on.",
        fix=["Check whether a deployment is in progress; otherwise disable maintenance mode."],
        commands=["bin/magento maintenance:status", "bin/magento maintenance:disable"],
    ),
    KnownIssue(
        id="mail-send-failed",
        title="E-mail could not be sent",
        pattern=r"Unable to send mail|MailException|Connection could not be established with host",
        area="E-mail",
        severity="medium",
        cause="Magento could not hand the message to a mail server: SMTP is not configured, the host is unreachable, or credentials are wrong. Order and account e-mails are not delivered.",
        fix=[
            "Check Stores > Configuration > Advanced > System > Mail Sending Settings (and any SMTP extension).",
            "For local docker-magento, point mail at the mailcatcher service to capture messages.",
        ],
        commands=["bin/magento config:show system/smtp"],
    ),
    KnownIssue(
        id="amqp-not-configured",
        title="RabbitMQ (AMQP) not configured",
        pattern=r'required connection "?amqp"? is not configured',
        area="Message queues",
        severity="info",
        cause="Queue consumers that prefer RabbitMQ are skipped because no AMQP connection is configured in app/etc/env.php. Harmless if the store relies on MySQL queues.",
        fix=["Configure the 'queue' > 'amqp' section in env.php if RabbitMQ is available; otherwise this can be ignored."],
        commands=["bin/magento setup:config:set --amqp-host=rabbitmq --amqp-port=5672 --amqp-user=guest --amqp-password=guest", "bin/magento queue:consumers:list"],
    ),
    KnownIssue(
        id="debug-logging-noise",
        title="Debug logging is enabled",
        pattern=r"^cache_invalidate:|Add of item with id .* was processed",
        area="Configuration",
        severity="info",
        cause="Debug logging writes every cache invalidation and admin menu build to debug.log. Useful in development, but it grows the log quickly and hides real problems.",
        fix=["Disable debug logging outside development."],
        commands=["bin/magento setup:config:set --enable-debug-logging=false", "bin/magento cache:flush"],
    ),
    KnownIssue(
        id="broken-layout-reference",
        title="Broken layout reference",
        pattern=r"^Broken reference:",
        area="Theme / layout",
        severity="info",
        cause="A layout XML instruction references a block or container that does not exist in the current page layout. Usually theme noise, but it can mean a block silently disappeared.",
        fix=["Find the named element in your theme or module layout XML and correct or remove the reference."],
        commands=["grep -rn \"<element name>\" app/design app/code"],
    ),
    KnownIssue(
        id="collection-duplicate-id",
        title="Duplicate item ID in a collection",
        pattern=r"with the same ID .* already exists",
        area="Code / catalog",
        severity="medium",
        cause="A collection load returned the same entity twice — typically a custom join (e.g. to a store or attribute table) without grouping, or duplicate rows in a URL rewrite / category link table.",
        fix=[
            "Use the stack trace to find which collection is loading and which module added the join.",
            "Add a group-by on the entity ID or fix the duplicate rows in the joined table.",
        ],
    ),
    KnownIssue(
        id="session-size-exceeded",
        title="Session size limit exceeded",
        pattern=r"Session size of \d+ exceeded allowed session max size",
        area="Sessions",
        severity="medium",
        cause="A customer or admin session grew beyond the configured maximum, so Magento dropped its data (users may be logged out or lose carts).",
        fix=[
            "Find what is stored in the session (large quotes, custom module data).",
            "If legitimate, raise Stores > Configuration > Advanced > System > Security > Max Session Size.",
        ],
        commands=["bin/magento config:show system/security/max_session_size_admin"],
    ),
    KnownIssue(
        id="code-generation-source-missing",
        title="Generated class has no source",
        pattern=r"Source class .* generation does not exist|Class .* does not exist",
        area="Code generation",
        severity="medium",
        cause="DI configuration or a constructor refers to a class that is not installed (for example an optional PHP extension's classes) or generated code is stale.",
        fix=[
            "Check which module references the class and whether its dependency is installed.",
            "Clear generated code and recompile.",
        ],
        commands=["rm -rf generated/code/* generated/metadata/*", "bin/magento setup:di:compile"],
    ),
    KnownIssue(
        id="php-warning-in-custom-code",
        title="PHP warning in custom code",
        pattern=r"(Warning|Notice|Deprecated): .* in /var/www/html/app/code/|Undefined (array key|index|variable)",
        area="Code / custom module",
        severity="medium",
        cause="A PHP warning in project code was converted to an exception by Magento's error handler (developer mode or strict error reporting).",
        fix=["Open the file and line named in the message and guard the missing key or variable; add a unit test for the input that triggered it."],
    ),
    KnownIssue(
        id="commerce-data-export-indexer",
        title="Commerce Data Export indexer could not be scheduled",
        pattern=r"CDE04-02|Cannot set indexer to Update On Schedule",
        area="SaaS data export",
        severity="low",
        cause="During installation the data-export feed tried to switch an indexer to 'Update by Schedule' before the related entity types existed.",
        fix=["After installation completes, check indexer modes and set the feed indexers to schedule mode."],
        commands=["bin/magento indexer:info", "bin/magento indexer:set-mode schedule"],
    ),
    KnownIssue(
        id="disk-space-low",
        title="Disk space running low",
        pattern=r"Disk (usage|space)|No space left on device",
        area="Infrastructure",
        severity="high",
        cause="The volume holding Magento is nearly full. Logs, reports, cache and sessions stop being written and checkout can fail.",
        fix=["Free space in var/log, var/report and var/cache; set up log rotation.", "Check database and media volumes too."],
        commands=["du -sh var/* pub/media", "bin/magento cache:clean"],
    ),
    KnownIssue(
        id="http-5xx",
        title="Server errors on storefront requests",
        pattern=r"^server_error ",
        area="Web server",
        severity="high",
        cause="Nginx returned 5xx responses: PHP-FPM is down or overloaded (502/504), or PHP raised a fatal error (500).",
        fix=[
            "Match the time of the 5xx burst with exception.log and system.log entries.",
            "Check PHP-FPM health and worker limits; look for var/report files from the same minute.",
        ],
        commands=["docker compose ps phpfpm", "ls -lt var/report | head"],
    ),
]

_COMPILED = [(issue, re.compile(issue.pattern, re.IGNORECASE)) for issue in KNOWN_ISSUES]
_BY_ID = {issue.id: issue for issue in KNOWN_ISSUES}


def get_issue(issue_id: str) -> Optional[KnownIssue]:
    return _BY_ID.get(issue_id)


def match_issues(*texts: Optional[str]) -> List[KnownIssue]:
    """All known issues whose pattern matches any of ``texts`` (message, exception, template)."""
    values = [text for text in texts if isinstance(text, str) and text]  # ignore None/NaN from pandas
    return [issue for issue, pattern in _COMPILED if any(pattern.search(text) for text in values)]


def match_issue(*texts: Optional[str]) -> Optional[KnownIssue]:
    matches = match_issues(*texts)
    return matches[0] if matches else None


def summarize_known_issues(rows: Iterable[dict], limit: int = 12) -> List[dict]:
    """Group template-level rows ({template, count, level, exception?}) by matched issue."""
    grouped: dict = {}
    for row in rows:
        issue = match_issue(row.get("template"), row.get("exception"), row.get("message"))
        if issue is None:
            continue
        entry = grouped.setdefault(issue.id, {**issue.to_dict(), "count": 0, "examples": []})
        entry["count"] += int(row.get("count", 1))
        example = row.get("template") or row.get("message")
        if example and example not in entry["examples"] and len(entry["examples"]) < 3:
            entry["examples"].append(example)
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(grouped.values(), key=lambda item: (order.get(item["severity"], 9), -item["count"]))[:limit]
