from app.services.log_service import process_log_file
from app.core.logger import logger
from app.config.settings import settings
from rich import print

if __name__ == "__main__":
    log_file = settings.log_file_path
    logger.info("Processing log file started")
    print("[green]Log Processing Started[/green]")
    process_log_file(log_file)