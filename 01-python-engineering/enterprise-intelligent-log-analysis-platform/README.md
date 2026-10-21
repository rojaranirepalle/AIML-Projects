# Enterprise Intelligent Log Analysis Platform

A local Python application that ingests application logs, normalizes records, computes operational analytics, flags high-severity events, exports reports, and exposes the pipeline through a REST API.

## Features

- Parses `LEVEL - message`, timestamped ISO-style records, and Hadoop log4j records (`YYMMDD HHMMSS PID LEVEL ...`). Unknown lines are retained as `UNKNOWN` so source evidence is not discarded.
- Normalizes each record to timestamp, severity, category, message, and source.
- Mines **log templates** with [Drain3](https://github.com/logpai/Drain3): block IDs, IPs, hex values and numbers are masked so lines describing the same event share one template (the 2,000-line HDFS sample reduces to 14 event types).
- Reports total volume, severity/category distributions, error rate, repeated messages, and severity-based indicators.
- Uses an Isolation Forest over two interpretable features per record — template rarity (`-log` of the template's share) and severity rank — to flag rare or severe event types. Results are listed per record and grouped per template; the model reports when the data is insufficient.
- Forecasts the next hourly or daily log and error counts from timestamped history using a transparent linear trend baseline.
- Can request an incident summary from an OpenAI-compatible chat completion API. This is disabled by default and sends only selected aggregate analytics and anomaly messages when enabled.
- Exports detailed CSV records and a JSON analytics summary.
- Provides a CLI and asynchronous FastAPI endpoints. API work runs outside the event loop.
- Includes a responsive operations dashboard at `/dashboard` for KPIs, severity distribution, forecast, top event templates, ML-flagged rare event types, recent events, and provider-generated incident briefs.
- Uses environment settings with working defaults; `.env` is optional.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

By default the app reads `data/HDFS_2k.log` (a 2,000-line sample of the [LogHub HDFS dataset](https://github.com/logpai/loghub)) and writes `logs/log_summary.csv` and `logs/analytics_summary.json`. A tiny `data/sample.log` is also included. Generated files in `logs/` are not committed.

Choose paths explicitly:

```bash
python main.py --input /path/to/application.log \
  --report output/records.csv --summary output/summary.json
```

## REST API

Start the API bound to localhost:

```bash
python main.py --api
```

Open `http://127.0.0.1:8000/docs` for interactive API documentation. Endpoints:

- `GET /dashboard` — visual operations dashboard.
- `GET /dashboard-data` — one analyzed snapshot for the dashboard.

- `GET /health` — process health check.
- `POST /analyze` — analyze a file and write the configured CSV/JSON reports. Body fields: `input_path`, `report_path`, and `summary_path`.
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
| `LOG_FILE_PATH` | `data/HDFS_2k.log` | Default input log |
| `REPORT_FILE_PATH` | `logs/log_summary.csv` | Default detailed CSV report |
| `SUMMARY_FILE_PATH` | `logs/analytics_summary.json` | Default analytics report |
| `LOG_LEVEL` | `INFO` | Application logging level |
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

Set `INCIDENT_SUMMARY_ENABLED=true` and choose `INCIDENT_SUMMARY_PROVIDER=openai`, `anthropic`, or `gemini`. The integration uses each provider's native request format. It sends a compact analytics summary and selected anomaly messages; do not enable it for sensitive logs unless your data policy allows that provider.

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

The suite (33 tests) covers every parser format, Drain3 template masking, summary metrics, the anomaly model, the forecast, report export, and each API endpoint via FastAPI's `TestClient`. No network access or API keys are needed.

## Architecture

```
raw log file
  → app/parsers/log_parser.py       parse each line into a LogEntry (app/models)
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
│   ├── parsers/          log_parser, template_miner
│   ├── services/         log_service, incident_summarizer
│   └── static/           dashboard.html
├── data/                 sample input logs
├── logs/                 generated reports (git-ignored)
├── tests/                pytest suite
└── main.py               CLI entry point
```

## Scope and next steps

ML anomaly scores and forecasts are exploratory batch-level signals, not calibrated operational alerts. Isolation Forest is refit on each uploaded batch and its scores only rank records within that batch, and the forecast is a linear baseline that needs sufficient timestamp coverage. Validate both against historical incidents before using them for paging decisions. Provider-generated summaries require credentials for a compatible service and are never fabricated when unavailable. Treat log content as sensitive when choosing a provider.
