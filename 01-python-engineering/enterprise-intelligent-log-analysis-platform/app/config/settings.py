from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Enterprise Intelligent Log Analysis Platform"
    log_file_path: Path = PROJECT_ROOT / "data" / "samples"
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

    # Live monitoring (python main.py --monitor)
    monitor_enabled: bool = False
    magento_log_dir: Optional[Path] = None
    monitor_db_path: Path = PROJECT_ROOT / "data" / "monitor.db"
    monitor_poll_seconds: float = Field(default=2.0, gt=0)
    alert_cooldown_minutes: int = Field(default=15, ge=0)
    alert_spike_window_minutes: int = Field(default=5, ge=1)
    alert_spike_min_errors: int = Field(default=10, ge=1)
    alert_spike_factor: float = Field(default=3.0, gt=0)

    # Optional e-mail alerts (for Gmail use an app password, not the account password)
    alert_email_enabled: bool = False
    alert_email_to: Optional[str] = None
    alert_email_from: Optional[str] = None
    alert_email_min_severity: str = "high"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[SecretStr] = None

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )


settings = Settings()
