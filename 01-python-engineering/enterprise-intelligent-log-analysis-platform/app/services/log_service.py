from pathlib import Path
from typing import List, Optional, Tuple, Union

from app.analytics.access_analytics import analyze_access, records_from_raw
from app.analytics.pandas_analytics import generate_summary
from app.config.settings import settings
from app.core.logger import logger
from app.data_processing.dataframe_builder import logs_to_dataframe
from app.models.log_model import LogEntry
from app.parsers.log_parser import iter_records, parse_log_line
from app.parsers.template_miner import add_templates
from app.reports.report_generator import export_report


LOG_GLOB = "*.log"


def list_log_files(path: Union[str, Path]) -> List[Path]:
    """Return ``[path]`` for a file, or the ``*.log`` files of a directory (e.g. Magento ``var/log``)."""
    source = Path(path)
    if source.is_file():
        return [source]
    if source.is_dir():
        return sorted(item for item in source.glob(LOG_GLOB) if item.is_file())
    raise FileNotFoundError(f"Log file or directory not found: {source}")


def read_entries(source: Path) -> Tuple[List[LogEntry], int]:
    """Parse one UTF-8 log file into entries; return them with the count of malformed records."""
    entries: List[LogEntry] = []
    skipped = 0
    with source.open("r", encoding="utf-8", errors="replace") as log_file:
        # Records may span several lines (Magento exception stack traces).
        for line_number, record in iter_records(log_file):
            try:
                entries.append(parse_log_line(record, source=source.name))
            except (ValueError, TypeError) as error:
                skipped += 1
                logger.warning("Skipping malformed record at %s:%d: %s", source.name, line_number, error)
    return entries, skipped


def process_log_file(
    file_path: Union[str, Path],
    report_path: Optional[Union[str, Path]] = None,
    summary_path: Optional[Union[str, Path]] = None,
) -> dict:
    """Ingest a log file or a directory of ``*.log`` files, analyze, and export reports."""
    source = Path(file_path)
    files = list_log_files(source)
    logger.info("Processing %s (%d file(s))", source, len(files))

    parsed_logs: List[LogEntry] = []
    skipped_lines = 0
    for log_file in files:
        entries, skipped = read_entries(log_file)
        parsed_logs.extend(entries)
        skipped_lines += skipped

    # Records from several files are analyzed together, in time order where known.
    if len(files) > 1:
        parsed_logs.sort(key=lambda entry: (entry.timestamp is None, entry.timestamp.timestamp() if entry.timestamp else 0))

    df = add_templates(logs_to_dataframe(parsed_logs))
    summary = generate_summary(df, contamination=settings.anomaly_contamination)
    summary["source_file"] = str(source)
    summary["source_files"] = [item.name for item in files]
    summary["source_distribution"] = df["source"].value_counts().to_dict() if not df.empty else {}
    summary["skipped_lines"] = skipped_lines
    access_rows = df[df["channel"] == "nginx"] if "channel" in df else df.iloc[0:0]
    summary["access"] = analyze_access(records_from_raw(access_rows["raw"].tolist())) if not access_rows.empty else {"available": False}

    if report_path is not None:
        exports = export_report(df, report_path, summary, summary_path)
        summary["reports"] = exports
        logger.info("Reports written: %s", exports)

    logger.info("Processed %d records (%d skipped)", len(df), skipped_lines)
    return {"summary": summary, "records": df.to_dict(orient="records")}
