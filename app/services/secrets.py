from __future__ import annotations

import json
from pathlib import Path

from ..db import DATA_DIR

SERVICE_NAME = "YT News Studio"
SETTINGS_PATH = DATA_DIR / "ai_settings.json"
SUPPORTED_PROVIDERS = {"openai", "anthropic"}
DEFAULT_SETTINGS = {
    "research_provider": "codex_local",
    "research_model": "default",
    "writer_provider": "codex_local",
    "writer_model": "default",
    "reviewer_provider": "claude_local",
    "reviewer_model": "default",
    "prefer_api_providers": False,
}


def get_api_key(provider: str) -> str | None:
    if provider not in SUPPORTED_PROVIDERS:
        return None
    try:
        import keyring
        return keyring.get_password(SERVICE_NAME, provider)
    except Exception:
        return None


def set_api_key(provider: str, value: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported provider")
    value = value.strip()
    if not value:
        raise ValueError("API key cannot be empty")
    import keyring
    keyring.set_password(SERVICE_NAME, provider, value)


def delete_api_key(provider: str) -> None:
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported provider")
    try:
        import keyring
        keyring.delete_password(SERVICE_NAME, provider)
    except Exception:
        pass


def load_ai_settings() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_PATH.exists():
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                settings.update({k: v for k, v in raw.items() if k in settings and isinstance(v, (str, bool))})
        except Exception:
            pass
    return settings


def save_ai_settings(values: dict) -> dict:
    settings = load_ai_settings()
    for key in DEFAULT_SETTINGS:
        if key in values and isinstance(values[key], type(DEFAULT_SETTINGS[key])):
            settings[key] = values[key]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def masked_status() -> dict:
    return {
        **load_ai_settings(),
        "openai_configured": bool(get_api_key("openai")),
        "anthropic_configured": bool(get_api_key("anthropic")),
    }
