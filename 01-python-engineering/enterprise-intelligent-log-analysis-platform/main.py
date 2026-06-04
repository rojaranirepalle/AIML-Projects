from rich import print

from app.services.log_service import process_log_file
from app.config.settings import settings


if __name__ == "__main__":

    print("[bold green]Enterprise Log Analysis Started[/bold green]")

    process_log_file(settings.log_file_path)

    print("[bold blue]Processing Completed[/bold blue]")