from app.parsers.log_parser import parse_log_line
from app.core.logger import logger

from app.data_processing.dataframe_builder import logs_to_dataframe
from app.analytics.pandas_analytics import generate_summary
from app.reports.report_generator import export_report


def process_log_file(file_path: str):

    logger.info("Log processing started")

    parsed_logs = []

    try:

        with open(file_path, "r") as file:

            for line in file:

                try:

                    parsed = parse_log_line(line)

                    parsed_logs.append(parsed)

                except Exception as parse_error:

                    logger.error(
                        f"Failed to parse line: {parse_error}"
                    )

    except FileNotFoundError:

        logger.error(
            f"Log file not found: {file_path}"
        )

        return

    except Exception as e:

        logger.error(
            f"Unexpected error: {e}"
        )

        return

    df = logs_to_dataframe(parsed_logs)

    logger.info("DataFrame Created")
    logger.info(f"\n{df}")

    analytics = generate_summary(df)

    logger.info("Pandas Analytics Summary")
    logger.info(analytics)

    export_report(df)

    logger.info(
        "CSV report generated successfully"
    )

    logger.info("Log processing completed")