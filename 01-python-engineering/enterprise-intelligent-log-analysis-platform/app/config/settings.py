from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Enterprise Intelligent Log Analysis Platform"
    log_file_path: Path = PROJECT_ROOT / "data" / "HDFS_2k.log"
    report_file_path: Path = PROJECT_ROOT / "logs" / "log_summary.csv"
    summary_file_path: Path = PROJECT_ROOT / "logs" / "analytics_summary.json"
    log_level: str = "INFO"
    anomaly_contamination: float = Field(default=0.02, gt=0, le=0.5)
    incident_summary_enabled: bool = False
    incident_summary_provider: str = "openai"
    incident_summary_api_base: Optional[str] = None
    incident_summary_api_key: Optional[SecretStr] = None
    openai_api_key: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None
    gemini_api_key: Optional[SecretStr] = None
    incident_summary_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-haiku-4-5-20251001"
    gemini_model: str = "gemini-3.5-flash-lite"
    incident_summary_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )


settings = Settings()
