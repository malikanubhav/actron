"""Settings from the environment and `.env`, validated once at startup (spec A, A1).

Every value may be empty: empty means "stub" or "not connected", never a crash.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

IntegrationStatus = Literal["live", "stub", "not_connected"]


class SettingsError(RuntimeError):
    """A setting is invalid. The message names the setting."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    ACTRON_ENV: Literal["dev", "prod", "test"] = "dev"
    ACTRON_SECRET_KEY: str | None = None
    SESSION_SECRET: str | None = None
    ACTRON_HOST: str = "127.0.0.1"
    ACTRON_PORT: int = 8080
    ACTRON_PUBLIC_URL: str | None = None
    ACTRON_ONTOLOGY_DIR: Path = REPO_ROOT / "ontology"
    ACTRON_LOG_LEVEL: str = "INFO"
    # Workspace that dev login creates or joins (the e2e stack uses its own).
    ACTRON_DEV_WORKSPACE: str = Field("dev", pattern=r"^[a-z0-9][a-z0-9-]{0,30}$")

    DATABASE_URL: str = "postgresql+psycopg://actron:actron@127.0.0.1:5433/actron"
    REDIS_URL: str = "redis://127.0.0.1:6380/0"
    FALKORDB_URL: str = "redis://127.0.0.1:6389"
    FALKORDB_GRAPH_PREFIX: str = "actron"
    # "params" uses the client's query parameters. "literal" is the safe literal binder (spec A, A4).
    FALKORDB_BINDING: Literal["params", "literal"] = "params"
    # Unique constraints on node ids. Default: on, except ACTRON_ENV=test (see docs/falkordb.md, limitation 12).
    FALKORDB_UNIQUE_CONSTRAINTS: bool | None = None
    TEMPORAL_ADDRESS: str = "127.0.0.1:7233"
    TEMPORAL_NAMESPACE: str = "actron"
    TEMPORAL_UI_PORT: int = 8233

    SLACK_BOT_TOKEN: str | None = None
    SLACK_SIGNING_SECRET: str | None = None
    SLACK_APP_TOKEN: str | None = None
    SLACK_CHANNELS: str | None = None
    SLACK_CLIENT_ID: str | None = None
    SLACK_CLIENT_SECRET: str | None = None
    SLACK_API_URL: str = "https://slack.com/api/"

    GITHUB_TOKEN: str | None = None
    GITHUB_REPOSITORY: str | None = None
    GITHUB_FORK: str | None = None
    GITHUB_UPSTREAM: str | None = None
    GITHUB_WEBHOOK_SECRET: str | None = None
    GITHUB_API_URL: str = "https://api.github.com"
    # Base for clone and push URLs (`<base>/<owner>/<name>.git`). The e2e stack points it at local bare repositories.
    GITHUB_GIT_URL: str = "https://github.com"

    LINEAR_API_KEY: str | None = None
    LINEAR_TEAM_ID: str | None = None
    LINEAR_API_URL: str = "https://api.linear.app/graphql"
    # Per-call timeout for Linear (the e2e stack lowers it to show the timeout state quickly).
    LINEAR_TIMEOUT_SECONDS: float = Field(30.0, gt=0, le=300)

    TYPESAFE_API_KEY: str | None = None
    JEV_MODEL: str = "jev-1.13.0"
    JEV_API_URL: str = "https://api.typesafe.ai/v1/systemone"
    ANTHROPIC_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    MODEL_DECISION: str | None = None
    MODEL_WRITING: str | None = None
    MODEL_AGENT: str | None = None
    MODEL_CODING: str | None = None
    LITELLM_FALLBACKS: str | None = None
    LINK_KEEP_THRESHOLD: float = Field(0.6, ge=0.0, le=1.0)
    CONFLICT_THRESHOLD: float = Field(0.8, ge=0.0, le=1.0)
    POSSIBLE_CONFLICT_THRESHOLD: float = Field(0.5, ge=0.0, le=1.0)

    ACTRON_BOT_NAME: str | None = None
    ACTRON_BOT_EMAIL: str | None = None
    ACTRON_MAX_CONCURRENT_BUILDS: int = Field(1, ge=1, le=16)
    ACTRON_BUILD_TIMEOUT_SECONDS: int = Field(1800, ge=30)
    ACTRON_MAX_REPAIRS: int = Field(2, ge=0, le=5)
    ACTRON_DAILY_MODEL_BUDGET_USD: float = Field(20.0, ge=0.0)
    ACTRON_BUILD_HOST_DIR: Path = Path("/var/lib/actron/builds")
    ACTRON_PI_IMAGE: str = "actron-pi:latest"
    # Non-secret variables for the Pi container, for the fake Pi in tests and the e2e stack (ignored in prod).
    ACTRON_PI_EXTRA_ENV: dict[str, str] = Field(default_factory=dict)
    ACTRON_TEST_RUNNER_IMAGE: str = "actron-test-runner:latest"
    ACTRON_MCP_URL: str = "http://worker:8765/mcp"
    ACTRON_MCP_PORT: int = 8765

    ACTRON_CLONE_DIR: Path = REPO_ROOT / ".actron" / "clones"
    ACTRON_BACKFILL_DAYS: int = Field(90, ge=1, le=3650)
    ACTRON_GIT_HISTORY_DEPTH: int = Field(2000, ge=1)

    API_INTERNAL_URL: str = "http://backend:8080"
    NEXT_PUBLIC_ACTRON_DEV_FIXTURES: str = "0"

    @model_validator(mode="before")
    @classmethod
    def _empty_is_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                k: (None if isinstance(v, str) and v.strip() == "" else v) for k, v in data.items()
            }
        return data

    @field_validator("DATABASE_URL")
    @classmethod
    def _check_db(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("must be a postgresql:// or postgresql+psycopg:// URL")
        return v

    @field_validator("REDIS_URL", "FALKORDB_URL")
    @classmethod
    def _check_redis(cls, v: str) -> str:
        if not v.startswith(("redis://", "rediss://")):
            raise ValueError("must be a redis:// URL")
        return v

    @field_validator("TEMPORAL_ADDRESS")
    @classmethod
    def _check_temporal(cls, v: str) -> str:
        host, _, port = v.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError("must be host:port")
        return v

    @field_validator("ACTRON_SECRET_KEY")
    @classmethod
    def _check_fernet(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from cryptography.fernet import Fernet

        try:
            Fernet(v.encode())
        except Exception as exc:
            raise ValueError("must be a Fernet key (32 url-safe base64 bytes)") from exc
        return v

    # Derived helpers
    @property
    def unique_constraints_enabled(self) -> bool:
        if self.FALKORDB_UNIQUE_CONSTRAINTS is not None:
            return self.FALKORDB_UNIQUE_CONSTRAINTS
        return self.ACTRON_ENV != "test"

    @property
    def is_dev(self) -> bool:
        return self.ACTRON_ENV in ("dev", "test")

    @property
    def slack_channels(self) -> list[str]:
        return [c.strip() for c in (self.SLACK_CHANNELS or "").split(",") if c.strip()]

    @property
    def litellm_fallbacks(self) -> list[str]:
        return [c.strip() for c in (self.LITELLM_FALLBACKS or "").split(",") if c.strip()]

    def model_for(self, job: Literal["decision", "writing", "agent", "coding"]) -> str | None:
        value: str | None = getattr(self, f"MODEL_{job.upper()}")
        return value

    def has_llm_key(self) -> bool:
        return any(
            [
                self.ANTHROPIC_API_KEY,
                self.OPENROUTER_API_KEY,
                self.GEMINI_API_KEY,
                self.GROQ_API_KEY,
                self.DEEPSEEK_API_KEY,
            ]
        )

    def integrations(self) -> dict[str, IntegrationStatus]:
        llm_live = self.has_llm_key() and any(
            [self.MODEL_DECISION, self.MODEL_WRITING, self.MODEL_AGENT, self.MODEL_CODING]
        )
        return {
            "jev": "live" if self.TYPESAFE_API_KEY else "stub",
            "llm": "live" if llm_live else "stub",
            "slack": "live" if self.SLACK_BOT_TOKEN else "not_connected",
            "github": "live" if self.GITHUB_TOKEN else "not_connected",
            "linear": "live" if self.LINEAR_API_KEY else "not_connected",
            "slack_oauth": "live"
            if (self.SLACK_CLIENT_ID and self.SLACK_CLIENT_SECRET)
            else "not_connected",
            "pi": "live" if (self.MODEL_CODING and self.has_llm_key()) else "stub",
        }

    def git_url(self, repo: str) -> str:
        """Clone and push URL of `owner/name` (no credentials; the token goes through a credential helper)."""
        return f"{self.GITHUB_GIT_URL.rstrip('/')}/{repo}.git"

    def secret_values(self) -> list[str]:
        """Every configured secret value, for log redaction."""
        out: list[str] = []
        for name in type(self).model_fields:
            if name.endswith(("KEY", "TOKEN", "SECRET")):
                value = getattr(self, name)
                if isinstance(value, str) and len(value) >= 6:
                    out.append(value)
        return out


def load_settings(**overrides: Any) -> Settings:
    """Build settings; raise SettingsError naming the first bad setting."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        err = exc.errors()[0]
        name = ".".join(str(p) for p in err.get("loc", ())) or "settings"
        raise SettingsError(f"Invalid setting {name}: {err.get('msg')}") from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
