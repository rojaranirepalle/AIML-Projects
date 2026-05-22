from app.parsers.log_parser import parse_log_line
from app.core.logger import logger

def process_log_file(file_path: str):
    logger.info("Log processing started")
    try:
        with open(file_path, "r") as file:
            for line in file:
                try:
                    parsed = parse_log_line(line)
                    logger.info(parsed)
                except Exception as parse_error:
                    logger.error(
                        f"Failed to parse line: {parse_error}"
                    )
    except FileNotFoundError:
        logger.error(f"Log file not found: {file_path}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    logger.info("Log processing completed")