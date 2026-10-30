import os
from pathlib import Path


def load_local_env() -> None:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


MODEL = os.getenv("MODEL", "openai/gpt-4.1-mini")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
TRAVEL_API_URL = os.getenv("TRAVEL_API_URL", "http://localhost:8103").rstrip("/")
TRAVEL_API_KEY = os.getenv("TRAVEL_API_KEY", "dev-key-change-me")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
WATCH_INTERVAL_SECONDS = max(60, int(os.getenv("WATCH_INTERVAL_SECONDS", "3600")))
VOICE_MODEL = os.getenv("VOICE_MODEL", "tiny")
VOICE_LANGUAGE = os.getenv("VOICE_LANGUAGE", "en").strip().lower()
if VOICE_LANGUAGE in {"", "auto"}:
    VOICE_LANGUAGE = None  # let Whisper auto-detect
VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() not in {"0", "false", "no"}
