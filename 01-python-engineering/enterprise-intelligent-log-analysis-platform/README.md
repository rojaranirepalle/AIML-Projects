# Enterprise Intelligent Log Analysis Platform

A local Python application for analyzing **logs from any application, service, or infrastructure**. Configure a log directory, investigate events in the dashboard and explorer, detect unusual patterns, generate reports, and optionally request AI explanations.

The platform supports generic text, ISO-timestamped, Hadoop/log4j, Magento/Monolog, and Nginx combined access logs. Unrecognized records are retained as `UNKNOWN`. Parsing and field extraction depend on the format; supporting logs from any source does not mean every format has a dedicated parser.

## Features

- **Operations dashboard:** needs-attention and overview views with severity distributions, error rates, event templates, exceptions, anomalies, forecasts, and recent events.
- **Settings tab:** a shared dashboard design with configuration for the log files root directory, active LLM provider, models, API keys, and AI enablement.
- **Log explorer:** search and filter by text, level, source file, exception, event template, and time range; inspect original records and stack traces.
- **Event templates:** Drain3 groups messages that differ only in variable values. Pattern-based masking covers emails, URLs, IPs, UUIDs, numeric values, and selected tokens and credentials.
- **Anomaly detection:** Isolation Forest ranks records using template rarity and severity, with per-record and per-template results.
- **Forecasting:** a linear baseline predicts the next hourly or daily event and error counts when enough timestamped data is available.
- **Live monitoring:** incremental file tailing, SQLite history, rotation and truncation handling, alert rules, and dashboard updates through Server-Sent Events.
- **Optional AI assistance:** OpenAI, Anthropic, or Google Gemini can explain events and summarize incidents. Rule-based explanations remain available without a provider.
- **Web traffic analytics:** Nginx combined access logs provide request counts, response-code distributions, latency percentiles, and route analysis.
- **Reports and API:** export normalized records to CSV and analytics to JSON, or use the FastAPI endpoints.
- **Specialized knowledge base:** built-in Adobe Commerce fixes enrich matching events. General log ingestion and analysis work independently of these specialized matches.

## Quick start

Run commands from this project folder. Use Python 3.11 or newer.

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`.

If you already use the portfolio's shared virtual environment, activate it instead of creating another one:

```bash
source ../../.venv/bin/activate
```

### 2. Start the application

```bash
python main.py --api --port 8000
```

Open:

- [Dashboard](http://127.0.0.1:8000/dashboard)
- [Log explorer](http://127.0.0.1:8000/explorer)
- [Settings](http://127.0.0.1:8000/settings)
- [Interactive API documentation](http://127.0.0.1:8000/docs)

Use another port if needed, for example `--port 8011`, and use that port in the browser URLs. Press **Ctrl+C** in Terminal to stop the application. Restart it after changing Python code; the server does not enable automatic reload.

### 3. Configure your logs

In **Settings → Log files**, enter the **Log files root directory path** and click **Save log directory**.

- Choose an existing, readable directory on the machine running the app.
- Absolute paths are supported. Relative paths entered in Settings resolve from the project folder; `~` expands to your home directory.
- Directory analysis loads `*.log` files directly inside the folder. Subdirectories are not scanned recursively.
- The source can contain logs from any application or service.
- Refresh the dashboard or explorer after saving to analyze the new source.

The initial source is `LOG_FILE_PATH`, defaulting to `data/samples`. Settings saves your selection in `data/source_settings.json`, which is git-ignored and persists across restarts.

The saved directory applies to **file-mode dashboard and explorer requests** and analysis API requests that omit `input_path`. An explicit API `input_path` takes precedence and may select an individual file with any extension.

**CLI batch analysis still uses `--input` or `LOG_FILE_PATH`. Live monitoring uses its startup `--log-dir` or `MAGENTO_LOG_DIR`.** Changing the directory in Settings does not switch a running monitor.

### 4. Configure optional AI assistance

In **Settings → LLM configuration**:

1. Choose the active provider: **OpenAI**, **Anthropic**, or **Google Gemini**.
2. Enter its API key and a model ID available to your provider account.
3. Enable **AI assistance** when you want provider-backed analysis.
4. Click **Save LLM configuration**.

You may configure all three providers and switch between them. Changes apply immediately to AI explanations and incident summaries; no restart is needed. Saving settings itself does not contact a provider.

API key fields are password inputs. The UI displays whether a key is configured and never retrieves the saved key. Leave a key field blank to retain its current value. Local overrides persist in the git-ignored `data/llm_settings.json` file with owner-only (`0600`) permissions. **This is local plaintext storage, not encrypted storage.**

Saved LLM values override the corresponding environment defaults. Provider-specific keys take precedence over the optional shared `INCIDENT_SUMMARY_API_KEY`. Remove the local overrides file to return to environment-based LLM configuration.

AI is disabled by default. When requested and enabled, AI analysis sends masked evidence or summaries to the selected provider. Masking is pattern-based and cannot guarantee removal of all sensitive information, especially names or identifiers inside free text.

## Batch analysis and reports

Run without `--api` to analyze logs once and write reports:

```bash
python main.py --input "/absolute/path/to/logs"
```

Or select a single file and report destinations:

```bash
python main.py --input "/absolute/path/to/application.log" \
  --report output/records.csv \
  --summary output/summary.json
```

Default output files are `logs/log_summary.csv` and `logs/analytics_summary.json`. Without `--input`, the CLI uses `LOG_FILE_PATH`, defaulting to `data/samples`.

To also request an incident summary after configuring and enabling AI:

```bash
python main.py --input "/absolute/path/to/logs" --incident-summary
```

## Live monitoring

Monitor a directory continuously:

```bash
python main.py --monitor --log-dir "/absolute/path/to/logs" --port 8000
```

This starts the API and live monitor together. Open the dashboard to view stored history, open alerts, and incoming updates.

Alternatively, set `MAGENTO_LOG_DIR=/absolute/path/to/logs` in `.env` and run `python main.py --monitor`. The variable name is retained for compatibility; **it accepts any log directory and does not require Magento**. `--log-dir` overrides it.

- Every immediate `*.log` file is tailed from its saved byte offset. New files are discovered automatically.
- Multi-line records are held until complete or until the file has been quiet long enough.
- Rotation and truncation are detected and the affected file is read from the beginning.
- Existing content on first startup is imported as a baseline without raising alerts. Restarts resume from saved offsets.
- SQLite history and Drain3 template state persist in `data/`. Only one monitor can use a database at a time.

Alert rules, with a default per-key cooldown of 15 minutes:

- **Critical level:** an `ALERT` or `EMERGENCY` record produces a critical alert.
- **New exception:** a previously unseen exception class produces a high-severity alert.
- **Error spike:** the recent error count reaches both the configured minimum and the configured multiple of its historical baseline, producing a high-severity alert.
- **New error template:** a previously unseen error-level event type produces a medium-severity alert.

Optional email alerts are configured through `.env`: set `ALERT_EMAIL_ENABLED=true`, recipients, sender, and SMTP credentials. Only alerts at or above `ALERT_EMAIL_MIN_SEVERITY` are sent. For Gmail, use an app password. Email alert text is masked before sending.

## Dashboard and explorer

The dashboard's **Show** chips combine Errors, Warnings, Info, and Debug filters. They recompute the log analytics for the selected levels; alerts and web traffic continue to describe the full input. The filter is stored in the URL and carried into explorer links.

Examples:

```text
/dashboard?level=error,warning
/dashboard-data?level=error,warning
/monitor/dashboard-data?level=error
/explorer/records?level=warning
```

Level groups and exact levels such as `CRITICAL` can be mixed. The Known issues & fixes card also offers its own issue-severity filters.

The explorer uses the monitoring store when a monitor exists; otherwise it uses the saved log source. Search records, select a file or exception, filter by event type or time range, and open a record for its raw text, stack trace, related occurrences, matching fixes, and AI explanation.

## AI assistant and specialized fixes

Use **Explain** on an alert, **Explain with AI** on a record, or **Ask the assistant** on the dashboard. The assistant gathers related evidence and returns a structured explanation covering the summary, likely cause, evidence, next checks, and possible fixes.

If AI is disabled, credentials are missing, or a provider request fails, the assistant returns a rule-based explanation. AI summaries are hypotheses to investigate, not confirmed root causes.

The current knowledge base in `app/knowledge/magento.py` contains Adobe Commerce-specific patterns, causes, and suggested commands. Matching fixes and suspect-frame selection include Magento conventions. These are specialized enrichments; generic logs still support parsing, search, templates, analytics, and AI explanations, but may have no built-in fix match. Review suggested commands for your environment before using them.

## Web traffic analytics

Nginx combined-format access logs, optionally followed by request time, are recognized automatically. A 5xx response becomes an error event in the shared pipeline. Traffic analytics include request volume, 4xx/5xx rates, latency percentiles where timing exists, bot share, grouped routes, and slow or failing routes. Route-area labels include commerce-oriented categories from the sample use case.

For container logs, write the relevant access-log lines to a `*.log` file inside the selected directory if you want file-based monitoring to ingest them.

## REST API

Start with `python main.py --api`. The API binds to `127.0.0.1:8000` by default. Interactive schemas are available at `/docs`.

Pages:

- `GET /dashboard` — operations dashboard.
- `GET /explorer` — log explorer.
- `GET /settings` — log source and LLM configuration.

Analysis:

- `GET /health` — service health.
- `GET /dashboard-data?input_path=...&level=...` — analyzed snapshot.
- `GET /summary?input_path=...` — analytics without report export.
- `POST /analyze` — analyze and export; optional body fields: `input_path`, `report_path`, `summary_path`.
- `POST /logs` — normalized records; body fields: `input_path`, `offset`, `limit` (maximum 1,000).
- `POST /incident-summary` — provider-generated summary; optional `input_path`, with AI enabled and configured.

Settings:

- `GET /settings/log-source` — current default log source.
- `PUT /settings/log-source` — save `{"log_file_path":"/absolute/path/to/logs","directory_only":true}`. The Settings form requires a directory; API clients may omit `directory_only` to save a single file instead.
- `GET /settings/llm` — AI enablement, provider, model names, and key-configured flags; never returns API keys.
- `PUT /settings/llm` — save `enabled`, `provider`, `openai_model`, `anthropic_model`, and `gemini_model`; optionally include provider API keys. Omitted or blank keys retain existing values.

Investigation:

- `GET /explorer/records` — filters: `input_path`, `q`, `level`, `source`, `exception`, `template_id`, `since`, `until`, `offset`, `limit`, `order`.
- `GET /explorer/records/{id}` — record details.
- `POST /assistant/explain` — explain an `alert_id`, `record_id`, `template_id`, or `question`.
- `GET /assistant/status` — provider availability.
- `GET /knowledge` and `GET /knowledge/match?text=...` — specialized knowledge entries and matches.

Monitoring:

- `GET /monitor/status`
- `GET /monitor/dashboard-data`
- `GET /monitor/alerts`
- `POST /monitor/alerts/{id}/ack`
- `GET /monitor/records?level=CRITICAL`
- `GET /monitor/stream` — Server-Sent Events (`records` and `alert`).

The application is intended for local use. Exposing it with `--host 0.0.0.0` requires appropriate access controls, including protection for settings endpoints and filesystem access.

## Environment configuration

The Settings tab handles the log analysis source and common LLM options. Additional settings can be supplied as environment variables or through a project-root `.env` file. Copy `.env.example` to `.env` if you do not already have one; do not overwrite existing credentials.

Common variables:

- `LOG_FILE_PATH`: default file or directory, initially `data/samples`; also used by CLI batch analysis.
- `REPORT_FILE_PATH` / `SUMMARY_FILE_PATH`: report destinations.
- `LOG_LEVEL`: application logging level, default `INFO`.
- `ANOMALY_CONTAMINATION`: expected anomalous share, default `0.02` (greater than zero and at most `0.5`).
- `MAGENTO_LOG_DIR`: any directory for live monitoring; overridden by `--log-dir`.
- `MONITOR_DB_PATH`: monitoring database, default `data/monitor.db`.
- `MONITOR_POLL_SECONDS`: polling interval, default `2`.
- `ALERT_COOLDOWN_MINUTES`, `ALERT_SPIKE_WINDOW_MINUTES`, `ALERT_SPIKE_MIN_ERRORS`, `ALERT_SPIKE_FACTOR`: alert controls.
- `ALERT_EMAIL_*` and `SMTP_*`: optional email delivery; see `.env.example`.

LLM environment defaults:

```dotenv
INCIDENT_SUMMARY_ENABLED=false
INCIDENT_SUMMARY_PROVIDER=openai
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
INCIDENT_SUMMARY_MODEL=gpt-4o-mini
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
GEMINI_MODEL=gemini-3.5-flash-lite
INCIDENT_SUMMARY_TIMEOUT_SECONDS=30
```

These model names are the application's configured defaults; choose a model supported by your provider account. `INCIDENT_SUMMARY_API_BASE` optionally supplies a custom endpoint base. `INCIDENT_SUMMARY_API_KEY` supplies a shared fallback key when a provider-specific key is absent. These advanced options remain environment-based.

Keep `.env`, local settings files, and real logs out of version control. Removing `data/source_settings.json` restores the `LOG_FILE_PATH` default for file-mode requests; removing `data/llm_settings.json` restores LLM environment defaults. Stop live monitoring before manually modifying or removing its database or template state.

## Sample data

The committed sample files are synthetic Adobe Commerce and Nginx logs. They demonstrate multi-line exceptions, cron and queue activity, failed logins, checkout errors, and a search outage; they do not limit the platform to that source.

Regenerate them with:

```bash
python scripts/generate_magento_sample.py --seed 7
```

Real logs placed in `data/` outside the committed sample directory are git-ignored.

## Testing

```bash
python -m pytest -q
```

Tests cover supported parser formats, stack traces, masking, templates, analytics, forecasting, reports, explorer filters, assistant fallback and mocked provider calls, tailing and rotation, monitoring alerts, API routes, and Settings persistence and validation. LLM settings tests verify key retention, owner-only file permissions, secret-free responses, and provider/model selection. No real API keys or external LLM calls are needed.

## Architecture

```text
log files
  → app/parsers/                   normalized records and multi-line grouping
  → app/data_processing/           stable-schema DataFrame
  → app/parsers/template_miner.py  Drain3 templates and masking
  → app/analytics/                 metrics, anomalies, forecasts, traffic analysis
  → app/reports/                   CSV records and JSON summaries
```

```text
├── app/
│   ├── analytics/         metrics, traffic, anomaly detection, forecasting
│   ├── config/            environment settings, saved log source, private LLM settings
│   ├── knowledge/         specialized Adobe Commerce fixes
│   ├── monitoring/        tailer, SQLite store, alerts, notifier, live routes
│   ├── parsers/           generic, ISO, Hadoop, Monolog, Nginx, Drain3
│   ├── services/          ingestion orchestration and provider integrations
│   ├── api.py             FastAPI application and analysis/settings routes
│   ├── assistant.py       evidence gathering and AI/rule-based explanations
│   ├── explorer.py        search and record-detail API
│   └── static/            dashboard.html, explorer.html, settings.html, theme.css
├── data/                  local logs, saved settings, monitor state, synthetic samples
├── logs/                  generated reports
├── scripts/               synthetic sample generator
├── tests/                 pytest suite
├── .env.example           configuration reference
├── requirements.txt       dependencies
└── main.py                CLI and server entry point
```

`main.py` and the API use `app/services/log_service.py` for batch analysis. The monitor incrementally parses and stores records in SQLite. LLM calls read the saved provider overrides at request time.

## Current limitations

- Folder ingestion and live monitoring currently select immediate `*.log` files, without recursive discovery or UI-configurable file patterns.
- The Settings log directory controls file-mode analysis, not CLI batch defaults or a running live monitor.
- Specialized issue matching and some dashboard labels still reflect the Adobe Commerce sample use case.
- Isolation Forest ranks events within the analyzed batch; scores are not calibrated operational risk probabilities. Forecasts are simple trend baselines requiring timestamp coverage.
- Masking reduces exposure but is not a guarantee of complete redaction. AI explanations require review against the actual evidence.
