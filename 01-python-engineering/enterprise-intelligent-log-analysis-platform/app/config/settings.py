from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Enterprise Log Analysis Platform"
    log_file_path: str = "logs/sample.log"


settings = Settings()