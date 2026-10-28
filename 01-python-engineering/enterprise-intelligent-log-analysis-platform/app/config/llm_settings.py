"""Local provider overrides. Secrets are never included in settings responses."""
import json
import os
import tempfile
import threading
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.config.settings import PROJECT_ROOT, settings

LLM_SETTINGS_PATH = PROJECT_ROOT / "data" / "llm_settings.json"
_lock = threading.Lock()
PROVIDER_FIELDS = {"openai": "incident_summary_model", "anthropic": "anthropic_model", "gemini": "gemini_model"}
router = APIRouter(prefix="/settings", tags=["settings"])


class LLMSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    provider: Literal["openai", "anthropic", "gemini"]
    openai_model: str = Field(min_length=1, max_length=200)
    anthropic_model: str = Field(min_length=1, max_length=200)
    gemini_model: str = Field(min_length=1, max_length=200)
    # Omitted or blank values retain the existing key. No secret is echoed back.
    openai_api_key: Optional[SecretStr] = None
    anthropic_api_key: Optional[SecretStr] = None
    gemini_api_key: Optional[SecretStr] = None


def _read() -> dict:
    try:
        return json.loads(LLM_SETTINGS_PATH.read_text())
    except FileNotFoundError:
        return {}


def effective_settings():
    data = _read()
    for key in ("openai_api_key", "anthropic_api_key", "gemini_api_key"):
        if key in data:
            data[key] = SecretStr(data[key])
    return settings.model_copy(update=data)


def public_settings() -> dict:
    config = effective_settings()
    result = {"enabled": config.incident_summary_enabled, "provider": config.incident_summary_provider}
    for provider, field in PROVIDER_FIELDS.items():
        result[f"{provider}_model"] = getattr(config, field)
        key = getattr(config, f"{provider}_api_key")
        shared = config.incident_summary_api_key
        result[f"{provider}_key_configured"] = bool(
            (key and key.get_secret_value().strip()) or (shared and shared.get_secret_value().strip())
        )
    result["shared_key_configured"] = bool(config.incident_summary_api_key and config.incident_summary_api_key.get_secret_value().strip())
    return result


def save_llm_settings(body: LLMSettingsRequest) -> dict:
    with _lock:
        data = _read()
        data.update(incident_summary_enabled=body.enabled, incident_summary_provider=body.provider)
        for provider, field in PROVIDER_FIELDS.items():
            model = getattr(body, f"{provider}_model").strip()
            if not model:
                raise ValueError("Model names cannot be blank.")
            data[field] = model
            secret = getattr(body, f"{provider}_api_key")
            if secret and secret.get_secret_value().strip():
                data[f"{provider}_api_key"] = secret.get_secret_value().strip()
        LLM_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=LLM_SETTINGS_PATH.parent, delete=False) as stream:
                temporary = stream.name
                os.chmod(temporary, 0o600)
                json.dump(data, stream)
            os.replace(temporary, LLM_SETTINGS_PATH)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    return public_settings()


@router.get("/llm")
def read_llm_settings() -> dict:
    try:
        return public_settings()
    except (OSError, ValueError):
        raise HTTPException(status_code=500, detail="Unable to read local LLM settings.")


@router.put("/llm")
def update_llm_settings(body: LLMSettingsRequest) -> dict:
    try:
        return save_llm_settings(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Model names cannot be blank or local settings are invalid.")
    except OSError:
        raise HTTPException(status_code=400, detail="Unable to save local LLM settings.")
