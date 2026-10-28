# Enterprise Intelligent Log Analysis Platform — Adobe Commerce

A local Python application for **Adobe Commerce (Magento 2) log intelligence**. It ingests `var/log` files, folds multi-line exception stack traces into single records, groups lines into event templates, flags rare or severe events with machine learning, forecasts volume, and exposes everything through a CLI, a REST API and an operations dashboard.

## Why Adobe Commerce

A busy Magento store writes thousands of `system.log`, `exception.log`, `debug.log` and `cron.log` lines a day. The signal an on-call developer needs — a new exception class, a one-off disk alert, a burst of checkout deadlocks, a search-engine outage — is buried under cron chatter, cache invalidations and "Broken reference" notices. This platform turns that stream into a ranked, explainable picture.

## Features

- **Magento / Monolog parsing.** Reads the `[timestamp] channel.LEVEL: message {context} [extra]` format, all eight PSR-3 levels (including `ALERT` and `EMERGENCY`), and separates the message from its JSON context.
- **Stack traces stay with their error.** `[previous exception]`, `[stacktrace]` and `#0 /var/www/...` lines are joined to the record that raised them; the exception class (for example `Zend_Db_Statement_Exception` or `Magento\Framework\Exception\MailException`) and the number of stack frames are extracted.
- **Event templates** with [Drain3](https://github.com/logpai/Drain3). Emails, URLs, UUIDs, hex tokens (quote masks, cache keys), IPs and numbers are masked, so 4,900 sample records reduce to 18 event types such as `Failed login attempt for customer <EMAIL> from <IP>`.
- **Anomaly detection.** An Isolation Forest over two interpretable features per record — template rarity (`-log` of the template's share) and severity rank — surfaces rare or severe event types. Results are listed per record and grouped per template.
- **Operational analytics.** Volume, severity, channel and category distributions, error rate, top exception classes, top templates and rule-based severity alerts.
- **Forecast.** Next hourly or daily log and error counts from a transparent linear trend baseline.
- **Privacy-aware incident briefs.** Optional summaries from OpenAI, Anthropic or Gemini. Disabled by default; when enabled only aggregates, templates and *masked* messages are sent — customer emails, URLs and tokens never leave the machine.
- **Reports, API and dashboard.** CSV records and a JSON summary; async FastAPI endpoints; a responsive pastel-themed dashboard at `/dashboard` with a **Needs attention** home (store health, open alerts, known issues & fixes, hourly errors/warnings) and an **Overview** view (KPIs, severity, traffic, forecast, top templates, exceptions, recent events).
- Still parses `LEVEL - message`, ISO-timestamped and Hadoop log4j lines; unrecognized lines are kept as `UNKNOWN` rather than discarded.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

By default the app reads the `data/samples/` directory (a Magento system log and an Nginx access log) and writes `logs/log_summary.csv` and `logs/analytics_summary.json`.

### Sample data

`data/samples/adobe_commerce_system.log` and `data/samples/nginx_access.log` are **synthetic**: three days of a fictional store (`shop.example.com`, an invented `Acme` vendor) with a daily traffic rhythm, cron and queue chatter, checkout deadlocks, failed logins, mail and payment errors, a 45-minute OpenSearch outage on day 3, and a few one-off events (an `ALERT` disk warning, an undefined-array-key bug in a custom module). Regenerate it with:

```bash
python scripts/generate_magento_sample.py --seed 7
```

### Your own store logs

Point `--input` at a single file or a whole log directory, e.g. `python main.py --input ~/magento/src/var/log`, or copy logs into `data/`. For continuous monitoring see [Live monitoring](#live-monitoring). Everything in `data/` except `data/samples/` is git-ignored, because real Magento logs contain customer emails, IP addresses and order details.

Choose paths explicitly:

```bash
python main.py --input /path/to/application.log \
  --report output/records.csv --summary output/summary.json
```

## Filtering by level

The **Show** chips under the dashboard header (Errors · Warnings · Info · Debug, combinable) recompute every log section — KPIs, severity, templates, exceptions, rare event types, known issues and recent events — for the selected levels. Alerts and web traffic always show everything. The choice is kept in the URL (`/dashboard?level=error,warning`) and carried into the explorer when you click through. The **Known issues & fixes** card has its own severity chips (High · Medium · Low · Info).

The same filter works in the API: `GET /dashboard-data?level=error,warning`, `GET /monitor/dashboard-data?level=error` and `GET /explorer/records?level=warning`; groups (`error`, `warning`, `info`, `debug`) and exact levels (`CRITICAL`) can be mixed.

## Known issues & fixes

`app/knowledge/magento.py` is a curated knowledge base of 20 common Adobe Commerce log events — search engine down, deadlocks and lock waits, "Area code is not set", missing media assets, InnoDB buffer pool, Braintree without credentials, cron not installed, maintenance mode, mail failures, session size, duplicate collection IDs, generated-class errors, PHP warnings in custom code, disk space, nginx 5xx and more. Each entry has the usual cause, fix steps and the `bin/magento` (or docker) commands to run.

Every event type in the analyzed logs is matched against it; the dashboard's **Known issues & fixes** card lists matches by severity with copyable commands. `GET /knowledge` lists all entries; `GET /knowledge/match?text=...` matches any text.

## Log explorer

`/explorer` searches every record — in live mode the monitoring store, otherwise the configured file or directory. Filter by text, level, file, exception class, event type and time range; open a record to see its full stack trace, how often its event type occurs, the matching fix, and an **Explain with AI** button. Dashboard template, exception and issue rows link straight into the explorer.

API: `GET /explorer/records?q=&level=ERROR,CRITICAL&source=&exception=&template_id=&since=&until=&offset=&limit=` and `GET /explorer/records/{id}`.

## Web traffic (Nginx access logs)

Access logs in the combined format (with an optional trailing request time) are recognized automatically in any analyzed file or monitored directory. They feed the shared pipeline (5xx responses become error events, so they raise alerts and match the "server errors" fix) and a **Web traffic** card: request volume, 5xx/4xx rates, p50/p95/p99 response time, bot share, requests and 5xx per Magento area (checkout, cart, REST, GraphQL, search, admin, static…), routes with 5xx errors and the slowest routes. URLs are grouped into routes (`/rest/default/V1/guest-carts/<ID>/items`), and client IPs are only reported as masked prefixes.

docker-magento's nginx logs to the container output rather than a file. To include it while monitoring, stream it into the watched folder from the Magento project directory:

```bash
docker compose logs -f --no-log-prefix --since 0s app \
  | grep --line-buffered -E '^[0-9a-fA-F.:]+ - ' >> src/var/log/nginx_access.log
```

## AI root-cause assistant

**Explain** on an alert, **Explain with AI** on a record, or the **Ask the assistant** box on the dashboard (`POST /assistant/explain` with `alert_id`, `record_id`, `template_id` or `question`). The assistant:

1. gathers evidence — the event and how often it occurs, a masked stack-trace excerpt, the *suspect frame* (first frame in `app/code`, then third-party modules, then Magento modules; framework libraries are skipped), other problems and web 5xx responses within ±10 minutes, recent alerts;
2. matches the evidence against the knowledge base, keeping issues that match the event itself separate from issues that only match nearby events; and
3. sends the masked evidence to the configured provider (OpenAI, Anthropic or Gemini, the same settings as incident briefs) for a structured answer — *Summary, Likely cause, Evidence, Check next, Fix*.

When no provider is enabled, or a request fails, it returns a rule-based explanation built from the same evidence, so the feature works offline. Emails, URLs, IPs, tokens and credentials are masked before anything leaves the machine. `GET /assistant/status` reports whether a provider is available.

## Live monitoring

Watch a Magento `var/log` directory continuously: new lines are parsed as they are written, stored in SQLite, checked against alert rules, and pushed to the dashboard.

```bash
# docker-magento (markshust) bind-mounts the container's var/ to src/var on the host
python main.py --monitor --log-dir ~/path/to/magento/src/var/log
# or set MAGENTO_LOG_DIR in .env and run
python main.py --monitor
```

Open `http://127.0.0.1:8000/dashboard`. In live mode it shows an **Alerts** panel, updates itself over Server-Sent Events when new records arrive, and runs analytics over the stored history instead of a single file.

How it works:

- **Tailing.** Every `*.log` file in the directory is read incrementally from a saved byte offset. Multi-line exception records are held until they are complete. Truncated or rotated files (for example after clearing `var/log`) are detected and re-read from the start, and new files are picked up automatically.
- **History without noise.** On first start, existing log content is imported as *baseline*: it builds the history and the known exceptions and event types, but raises no alerts. Restarts resume from the saved offsets, so lines written while the monitor was stopped are still checked, and no line is stored twice. Only one monitor can use a database at a time.
- **Stable templates.** Drain3 state is persisted next to the database, so template IDs survive restarts.
- **Alert rules** (each with a per-key cooldown, default 15 minutes):

  | Rule | Fires when | Severity |
  | --- | --- | --- |
  | `critical_level` | an `ALERT` or `EMERGENCY` record is logged | critical |
  | `new_exception` | an exception class appears that has never been seen before | high |
  | `error_spike` | errors in the last 5 minutes reach both `ALERT_SPIKE_MIN_ERRORS` and `ALERT_SPIKE_FACTOR` × the average 5-minute count over the previous 24 hours | high |
  | `new_error_template` | an error-level event type appears for the first time | medium |

- **E-mail alerts (optional).** Set `ALERT_EMAIL_ENABLED=true`, `ALERT_EMAIL_TO` and the SMTP settings; for Gmail use an app password. Only alerts at or above `ALERT_EMAIL_MIN_SEVERITY` are sent, and their text is masked (emails, URLs, IPs, tokens) before it leaves the machine.

Monitoring endpoints: `GET /monitor/status`, `GET /monitor/dashboard-data`, `GET /monitor/alerts`, `POST /monitor/alerts/{id}/ack`, `GET /monitor/records?level=CRITICAL`, and `GET /monitor/stream` (Server-Sent Events: `records` and `alert`). The database (`data/monitor.db`) and template state live in the git-ignored `data/` folder; delete both to start over.

## REST API

Start the API bound to localhost:

```bash
python main.py --api
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation. Endpoints:

- `GET /dashboard` — visual operations dashboard.
- `GET /dashboard-data` — one analyzed snapshot for the dashboard.

- `GET /health` — process health check.
- `POST /analyze` — analyze a file (or a directory of `*.log` files, such as Magento `var/log`) and write the configured CSV/JSON reports. Body fields: `input_path`, `report_path`, and `summary_path`.
- `GET /summary?input_path=...` — return analytics without writing reports.
- `POST /logs` — retrieve normalized records with `input_path`, `offset`, and `limit` (maximum 1,000 records per page).
- `POST /incident-summary` — request a provider-generated incident summary for `input_path`; requires the explicit provider configuration below.

The API is intended for local use and binds to `127.0.0.1` by default. Set `--host 0.0.0.0` only when you intend to expose it to a network and have added appropriate access controls.

## Configuration

Settings can be provided as environment variables or in a local `.env` file:

Copy `.env.example` to `.env` to start from the defaults. Keep `.env` and any real API key out of version control.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `Enterprise Intelligent Log Analysis Platform` | API service name |
| `LOG_FILE_PATH` | `data/samples` | Default input file or directory |
| `REPORT_FILE_PATH` | `logs/log_summary.csv` | Default detailed CSV report |
| `SUMMARY_FILE_PATH` | `logs/analytics_summary.json` | Default analytics report |
| `LOG_LEVEL` | `INFO` | Application logging level |
| `MAGENTO_LOG_DIR` | unset | Directory watched by `--monitor` (e.g. `<magento>/src/var/log`) |
| `MONITOR_DB_PATH` | `data/monitor.db` | SQLite database for monitored records and alerts |
| `ALERT_EMAIL_ENABLED` | `false` | Send alerts by e-mail (see `.env.example` for SMTP settings) |
| `ANOMALY_CONTAMINATION` | `0.02` | Expected share of records the Isolation Forest flags (0 < value ≤ 0.5) |
| `INCIDENT_SUMMARY_ENABLED` | `false` | Explicitly enable outbound incident summary requests |
| `INCIDENT_SUMMARY_PROVIDER` | `openai` | `openai`, `anthropic`, or `gemini` |
| `INCIDENT_SUMMARY_API_BASE` | provider default | Optional custom API base URL |
| `OPENAI_API_KEY` | unset | OpenAI API key when using OpenAI |
| `ANTHROPIC_API_KEY` | unset | Anthropic API key when using Claude |
| `GEMINI_API_KEY` | unset | Google Gemini API key |
| `INCIDENT_SUMMARY_API_KEY` | unset | Optional generic key override |
| `INCIDENT_SUMMARY_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Claude model name |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model name |
| `INCIDENT_SUMMARY_TIMEOUT_SECONDS` | `30` | Provider request timeout |

Set `INCIDENT_SUMMARY_ENABLED=true` and choose `INCIDENT_SUMMARY_PROVIDER=openai`, `anthropic`, or `gemini`. The integration uses each provider's native request format. It sends a compact analytics summary, event templates, exception class names and selected anomaly messages with emails, URLs, IPs, UUIDs and hex tokens masked. Masking is pattern-based and cannot catch every kind of personal data (for example names inside free text), so check your store's data policy before enabling it for production logs.

Example Claude configuration in `.env`:

```dotenv
INCIDENT_SUMMARY_ENABLED=true
INCIDENT_SUMMARY_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

For OpenAI, set `INCIDENT_SUMMARY_PROVIDER=openai`, `OPENAI_API_KEY`, and optionally `INCIDENT_SUMMARY_MODEL`. You can request the summary with `python main.py --incident-summary` or `POST /incident-summary`.

For Gemini, set `INCIDENT_SUMMARY_PROVIDER=gemini`, `GEMINI_API_KEY`, and optionally `GEMINI_MODEL`. Google’s Gemini API uses the `generateContent` endpoint; the default model is `gemini-3.5-flash-lite`. See [Google's model list](https://ai.google.dev/gemini-api/docs/models) for current available model IDs.

## Testing

```bash
pytest
```

The suite (93 tests) covers the knowledge base, access-log parsing and traffic analytics, explorer filters, the assistant (rule-based and mocked AI modes, masking, alert targets), every parser format including Magento stack traces, Drain3 template, PII and credential masking, incremental tailing (partial lines, rotation, truncation, restarts), alert rules and cooldowns, the monitoring endpoints, summary metrics, the anomaly model, the forecast, report export, and each API endpoint via FastAPI's `TestClient`. No network access or API keys are needed.

## Architecture

```
raw log file
  → app/parsers/log_parser.py       group multi-line records, parse each into a LogEntry (app/models)
  → app/data_processing/            build a stable-schema DataFrame
  → app/parsers/template_miner.py   add template_id / template (Drain3)
  → app/analytics/                  summary metrics, Isolation Forest, forecast
  → app/reports/                    CSV records + JSON summary
```

`main.py` is the CLI. `app/api.py` exposes HTTP routes. Both call `app/services/log_service.py`, which coordinates the pipeline above. `app/services/incident_summarizer.py` optionally sends the aggregate summary (including top and rare templates) to an LLM provider.

```
├── app/
│   ├── analytics/        forecasting, ml_anomaly, pandas_analytics
│   ├── config/           pydantic-settings configuration
│   ├── knowledge/        Adobe Commerce known issues and fixes
│   ├── monitoring/       tailer, SQLite store, alert rules, notifier, live API routes
│   ├── parsers/          log_parser (Monolog, Hadoop, generic), access_log (Nginx), template_miner
│   ├── services/         log_service, llm_client, incident_summarizer
│   ├── assistant.py      AI root-cause assistant
│   ├── explorer.py       log search API
│   └── static/           dashboard.html, explorer.html, theme.css (shared pastel theme, served under /static)
├── data/                 local store logs (git-ignored); data/samples/ is committed
├── logs/                 generated reports (git-ignored)
├── scripts/              synthetic Adobe Commerce sample generator
├── tests/                pytest suite
└── main.py               CLI entry point
```

## Scope and next steps

ML anomaly scores and forecasts are exploratory batch-level signals, not calibrated operational alerts. Isolation Forest is refit on each uploaded batch and its scores only rank records within that batch, and the forecast is a linear baseline that needs sufficient timestamp coverage. Validate both against historical incidents before using them for paging decisions. Provider-generated summaries require credentials for a compatible service and are never fabricated when unavailable. Treat log content as sensitive when choosing a provider.
