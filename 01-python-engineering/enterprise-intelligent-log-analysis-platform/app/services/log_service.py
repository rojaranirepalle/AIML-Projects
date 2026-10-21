from pathlib import Path
from typing import Optional, Union

from app.analytics.pandas_analytics import generate_summary
from app.config.settings import settings
from app.core.logger import logger
from app.data_processing.dataframe_builder import logs_to_dataframe
from app.parsers.log_parser import parse_log_line
from app.parsers.template_miner import add_templates
from app.reports.report_generator import export_report


def process_log_file(
    file_path: Union[str, Path],
    report_path: Optional[Union[str, Path]] = None,
    summary_path: Optional[Union[str, Path]] = None,
) -> dict:
    """Ingest a UTF-8 log file, normalize records, analyze, and export reports."""
    source = Path(file_path)
    if not source.is_file():
        raise FileNotFoundError(f"Log file not found: {source}")

    logger.info("Processing %s", source)
    parsed_logs = []
    skipped_lines = 0
    with source.open("r", encoding="utf-8", errors="replace") as log_file:
        for line_number, line in enumerate(log_file, start=1):
            if not line.strip():
                continue
            try:
                parsed_logs.append(parse_log_line(line, source=source.name))
            except (ValueError, TypeError) as error:
                skipped_lines += 1
                logger.warning("Skipping malformed line %d: %s", line_number, error)

    df = add_templates(logs_to_dataframe(parsed_logs))
    summary = generate_summary(df, contamination=settings.anomaly_contamination)
    summary["source_file"] = str(source)
    summary["skipped_lines"] = skipped_lines

    if report_path is not None:
        exports = export_report(df, report_path, summary, summary_path)
        summary["reports"] = exports
        logger.info("Reports written: %s", exports)

    logger.info("Processed %d records (%d skipped)", len(df), skipped_lines)
    return {"summary": summary, "records": df.to_dict(orient="records")}
