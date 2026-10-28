"""Persist the dashboard's default log source independently of secrets in .env."""
import json
import os
import tempfile
from pathlib import Path

from app.config.settings import PROJECT_ROOT, settings

SOURCE_SETTINGS_PATH = PROJECT_ROOT / "data" / "source_settings.json"


def get_log_path() -> Path:
    try:
        return Path(json.loads(SOURCE_SETTINGS_PATH.read_text())["log_file_path"])
    except FileNotFoundError:
        return settings.log_file_path


def save_log_path(value: str, directory_only: bool = False) -> Path:
    if not value.strip():
        raise ValueError("Enter a log file or folder path.")
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.exists():
        raise ValueError("The log path does not exist on the server.")
    if directory_only and not path.is_dir():
        raise ValueError("Choose a directory for the logs root path.")
    if path.is_file():
        with path.open("rb") as stream:
            stream.read(1)
    elif path.is_dir():
        # Force directory enumeration to verify read access.
        next(path.iterdir(), None)
    else:
        raise ValueError("Choose a regular file or directory.")
    SOURCE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=SOURCE_SETTINGS_PATH.parent, delete=False) as stream:
            temporary = stream.name
            json.dump({"log_file_path": str(path)}, stream)
        os.replace(temporary, SOURCE_SETTINGS_PATH)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return path
