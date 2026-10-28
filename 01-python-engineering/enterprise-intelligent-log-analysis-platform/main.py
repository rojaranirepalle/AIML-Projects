import argparse
import json
from pathlib import Path

from rich import print

from app.config.settings import settings
from app.services.log_service import process_log_file
from app.services.incident_summarizer import SummarizationError, summarize_incident


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse application logs and generate operational analytics."
    )
    parser.add_argument("--input", default=str(settings.log_file_path), help="Input log file")
    parser.add_argument("--report", default=str(settings.report_file_path), help="CSV report destination")
    parser.add_argument("--summary", default=str(settings.summary_file_path), help="JSON summary destination")
    parser.add_argument("--api", action="store_true", help="Run the local REST API")
    parser.add_argument("--monitor", action="store_true", help="Run the API with live monitoring of a log directory")
    parser.add_argument("--log-dir", help="Directory to monitor, e.g. <magento>/src/var/log (overrides MAGENTO_LOG_DIR)")
    parser.add_argument("--incident-summary", action="store_true", help="Request an opt-in provider-generated incident summary")
    parser.add_argument("--host", default="127.0.0.1", help="API bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="API port")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.monitor:
        if args.log_dir:
            settings.magento_log_dir = Path(args.log_dir).expanduser()
        if not settings.magento_log_dir or not Path(settings.magento_log_dir).expanduser().is_dir():
            print("[bold red]Set MAGENTO_LOG_DIR in .env or pass --log-dir with an existing directory.[/bold red]")
            return 1
        settings.monitor_enabled = True
        args.api = True
        print(f"[bold green]Monitoring[/bold green] {settings.magento_log_dir} — dashboard: http://{args.host}:{args.port}/dashboard")

    if args.api:
        try:
            import uvicorn
        except ImportError as error:
            raise SystemExit("Install the API dependencies with: pip install -r requirements.txt") from error
        # Bounded shutdown so open live-stream connections cannot keep the monitor running.
        uvicorn.run("app.api:app", host=args.host, port=args.port, reload=False, timeout_graceful_shutdown=3)
        return 0

    try:
        result = process_log_file(args.input, args.report, args.summary)
    except (FileNotFoundError, PermissionError, OSError) as error:
        print(f"[bold red]Processing failed:[/bold red] {error}")
        return 1

    print("[bold green]Log analysis complete[/bold green]")
    print(json.dumps(result["summary"], indent=2, default=str))
    if args.incident_summary:
        try:
            incident_summary = summarize_incident(result["summary"])
            print("[bold]Incident summary[/bold]")
            print(incident_summary)
        except SummarizationError as error:
            print(f"[bold red]Incident summary unavailable:[/bold red] {error}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
