import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env if present. Real environment variables win (override=False).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SQLITE_PREFIX = "sqlite:///"
MIN_KEYS = 2  # the assignment requires a pool of at least 2 API keys


def parse_database_url(url: str) -> str:
    """sqlite:////data/app.db -> /data/app.db ; sqlite:///./app.db -> ./app.db"""
    if not url.startswith(SQLITE_PREFIX):
        raise ValueError("DATABASE_URL must start with sqlite:///")
    path = url[len(SQLITE_PREFIX):]
    if not path:
        raise ValueError("DATABASE_URL has no file path")
    return path


def _split(value: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in value.split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    api_keys: tuple[str, ...] = field(repr=False)  # never printed
    db_path: str
    allowed_origins: tuple[str, ...]
    enable_failure_simulation: bool
    llm_model: str
    default_system_prompt: str
    llm_timeout: float

    @property
    def key_ids(self) -> list[str]:
        return [f"key_{i}" for i in range(1, len(self.api_keys) + 1)]


def get_settings() -> Settings:
    return Settings(
        api_keys=_split(os.getenv("LLM_API_KEYS", "")),
        db_path=parse_database_url(os.getenv("DATABASE_URL", "sqlite:///./app.db")),
        allowed_origins=_split(os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")),
        enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").strip().lower() == "true",
        llm_model=os.getenv("LLM_MODEL", "gemini/gemini-3.5-flash-lite"),
        default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful assistant."),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "30")),
    )
