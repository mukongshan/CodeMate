"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}

DEFAULT_COMMAND_ALLOWLIST = [
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "git status",
    "git diff",
]


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    api_key: str = ""
    base_url: Optional[str] = None
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0

    def __post_init__(self) -> None:
        default_url, default_model = PROVIDER_DEFAULTS.get(
            self.provider, PROVIDER_DEFAULTS["openai"]
        )
        if not self.base_url:
            self.base_url = default_url
        if not self.model:
            self.model = default_model

    def to_client_dict(self) -> dict:
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "retry": {
                "max_retries": self.max_retries,
                "base_delay": self.base_delay,
                "max_delay": self.max_delay,
            },
        }


@dataclass
class AppConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    workspace: Path = field(default_factory=Path.cwd)
    data_dir: Path = Path("data/sessions")
    log_dir: Path = Path("logs")
    command_allowlist: list[str] = field(
        default_factory=lambda: list(DEFAULT_COMMAND_ALLOWLIST)
    )
    cors_origins: list[str] = field(default_factory=list)
    max_iterations: int = 20
    max_context_tokens: int = 8000
    host: str = "127.0.0.1"
    port: int = 8000
    debug: bool = False

    @staticmethod
    def from_env() -> "AppConfig":
        provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()

        llm = LLMConfig(
            provider=provider,
            api_key=(os.getenv("LLM_API_KEY") or "").strip(),
            base_url=(os.getenv("LLM_BASE_URL") or "").strip() or None,
            model=(os.getenv("LLM_MODEL") or "").strip(),
            temperature=_float_env("LLM_TEMPERATURE", 0.7),
            max_tokens=_int_env("LLM_MAX_TOKENS", 2000),
            max_retries=_int_env("LLM_MAX_RETRIES", 3),
        )

        workspace = Path(os.getenv("WORKSPACE", ".")).expanduser().resolve()

        return AppConfig(
            llm=llm,
            workspace=workspace,
            data_dir=Path(os.getenv("DATA_DIR", "data/sessions")),
            log_dir=Path(os.getenv("LOG_DIR", "logs")),
            command_allowlist=_list_env(
                "COMMAND_ALLOWLIST",
                list(DEFAULT_COMMAND_ALLOWLIST),
            ),
            cors_origins=_list_env(
                "CORS_ORIGINS",
                [
                    "http://localhost:5173",
                    "http://127.0.0.1:5173",
                ],
            ),
            max_iterations=_int_env("MAX_ITERATIONS", 20),
            max_context_tokens=_int_env("MAX_CONTEXT_TOKENS", 8000),
            host=os.getenv("HOST", "127.0.0.1"),
            port=_int_env("PORT", 8000),
            debug=_bool_env("DEBUG", False),
        )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _list_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]
