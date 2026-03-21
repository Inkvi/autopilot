from __future__ import annotations

import logging
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import os
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from autopilot.channels.base import ChannelConfig


class GitChangesCondition(BaseModel):
    type: Literal["git_changes"]


class FileChangesCondition(BaseModel):
    type: Literal["file_changes"]
    paths: list[str]


class CommandCondition(BaseModel):
    type: Literal["command"]
    cmd: str


RunCondition = Annotated[
    GitChangesCondition | FileChangesCondition | CommandCondition,
    Field(discriminator="type"),
]

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(s|m|h|d)$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_ALLOWED_BACKENDS = {
    "claude_cli",
    "claude_sdk",
    "codex_cli",
    "openai_agents_sdk",
    "gemini_cli",
}


def is_cron_schedule(value: str) -> bool:
    """Check if a schedule string is a cron expression."""
    from croniter import croniter

    return croniter.is_valid(value.strip())


def parse_schedule(value: str) -> float:
    """Parse a human duration like '24h', '30m', '1d' into seconds.

    Also accepts cron expressions (e.g. '0 5 * * *'), returning 0.0
    since cron schedules are time-based, not interval-based.
    """
    value = value.strip()
    if is_cron_schedule(value):
        return 0.0  # cron schedules use next-fire-time logic, not intervals
    m = _DURATION_RE.match(value)
    if not m:
        raise ValueError(
            f"Invalid schedule: {value!r}. Use a duration (e.g. '30m', '1h', '24h') "
            f"or a cron expression (e.g. '0 5 * * *')."
        )
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]


_DEFAULT_SYSTEM_PROMPT = (
    "This is an unattended automation. "
    "Do not ask for confirmation — execute all steps autonomously."
)


class AutomationConfig(BaseModel):
    name: str
    prompt: str
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    working_directory: str | None = None
    repos: list[str] = []
    schedule: str | None = None
    backend: str | list[str] = "claude_cli"
    model: str | dict[str, str] | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 900
    skip_permissions: bool = True
    max_turns: int = 10
    max_retries: int = 0
    run_if: RunCondition | None = None
    channels: list[ChannelConfig] = []
    copy_files: list[str] = [".env", ".env.local", ".envrc"]
    skills: list[str] = []
    webhook_secret: str | None = None
    webhook_secret_env: str | None = None
    source_dir: Path | None = None

    @field_validator("backend", mode="before")
    @classmethod
    def validate_backend(cls, v: str | list[str]) -> str | list[str]:
        if isinstance(v, str):
            if v not in _ALLOWED_BACKENDS:
                raise ValueError(
                    f"Unknown backend {v!r}. Choose from: {', '.join(sorted(_ALLOWED_BACKENDS))}"
                )
            return v
        if not v:
            raise ValueError("backend list must not be empty")
        for b in v:
            if b not in _ALLOWED_BACKENDS:
                raise ValueError(
                    f"Unknown backend {b!r}. Choose from: {', '.join(sorted(_ALLOWED_BACKENDS))}"
                )
        return v

    @field_validator("reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, v: str | None) -> str | None:
        if v is not None and v not in {"low", "medium", "high", "max"}:
            raise ValueError(f"reasoning_effort must be low|medium|high|max, got {v!r}")
        return v

    @field_validator("copy_files")
    @classmethod
    def validate_copy_files(cls, v: list[str]) -> list[str]:
        for p in v:
            if Path(p).is_absolute():
                raise ValueError(f"copy_files path must be relative: {p!r}")
            if ".." in Path(p).parts:
                raise ValueError(f"copy_files path resolves outside working directory: {p!r}")
        return v

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, v: list[str]) -> list[str]:
        from autopilot.repos import parse_github_tree_url

        for url in v:
            parse_github_tree_url(url)  # raises ValueError if invalid
        return v

    @model_validator(mode="after")
    def check_trigger(self) -> AutomationConfig:
        if isinstance(self.model, dict):
            if not self.model:
                raise ValueError("model mapping must not be empty")
            unknown_backends = sorted(set(self.model) - set(self.backends))
            if unknown_backends:
                joined = ", ".join(unknown_backends)
                raise ValueError(f"model mapping contains unknown backend key(s): {joined}")

        has_schedule = self.schedule is not None
        has_webhook = self.webhook_secret is not None or self.webhook_secret_env is not None
        if not has_schedule and not has_webhook:
            raise ValueError(
                "Automation must have at least one trigger: "
                "set 'schedule' and/or 'webhook_secret'/'webhook_secret_env'"
            )
        return self

    def resolve_webhook_secret(self) -> str:
        """Resolve the webhook secret, checking env var if needed."""
        if self.webhook_secret:
            return self.webhook_secret
        if self.webhook_secret_env:
            secret = os.environ.get(self.webhook_secret_env)
            if not secret:
                raise RuntimeError(f"Environment variable {self.webhook_secret_env!r} is not set")
            return secret
        raise RuntimeError("No webhook secret configured")

    @property
    def schedule_seconds(self) -> float:
        if self.schedule is None:
            return 0.0
        return parse_schedule(self.schedule)

    @property
    def backends(self) -> list[str]:
        if isinstance(self.backend, str):
            return [self.backend]
        return self.backend

    @property
    def primary_backend(self) -> str:
        return self.backends[0]

    def model_for_backend(self, backend_name: str) -> str | None:
        if self.model is None:
            return None
        if isinstance(self.model, str):
            if len(self.backends) == 1 or backend_name == self.primary_backend:
                return self.model
            return None
        return self.model.get(backend_name)

    @property
    def model_display(self) -> str:
        if self.model is None:
            return "default"
        if isinstance(self.model, str):
            return self.model
        return ", ".join(
            f"{backend}={self.model[backend]}" for backend in self.backends if backend in self.model
        )

    @property
    def cwd(self) -> Path | None:
        if self.working_directory is None:
            return None
        return Path(self.working_directory).expanduser().resolve()

    @property
    def skills_dir(self) -> Path | None:
        if self.source_dir and (self.source_dir / "skills").is_dir():
            return self.source_dir / "skills"
        return None


def parse_name_list(value: str | None) -> list[str] | None:
    """Parse a comma-separated string into a list of names, or None if empty/unset."""
    if not value or not value.strip():
        return None
    return [name.strip() for name in value.split(",") if name.strip()]


def load_base_config(automations_dir: Path) -> dict | None:
    """Load base.toml from automations directory if it exists."""
    base_path = automations_dir / "base.toml"
    if not base_path.exists():
        return None
    with open(base_path, "rb") as f:
        return tomllib.load(f)


def load_automation(directory: Path, base_config: dict | None = None) -> AutomationConfig:
    """Load an automation config from a directory containing config.toml."""
    config_path = directory / "config.toml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.toml found in {directory}")
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    if base_config is not None:
        for key in ("name", "prompt"):
            if key in base_config:
                raise ValueError(f"base.toml must not contain '{key}'")
        data = {**base_config, **data}
    config = AutomationConfig(**data)
    config.source_dir = directory.resolve()
    return config


def discover_automations(
    directory: Path,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[AutomationConfig]:
    """Discover all folder-based automation configs in a directory.

    Args:
        directory: Path to automations directory.
        include: If set, only load automations whose folder name is in this list.
        exclude: If set, skip automations whose folder name is in this list.
    """
    if not directory.is_dir():
        return []

    flat_tomls = sorted(p for p in directory.glob("*.toml") if p.name != "base.toml")
    if flat_tomls:
        names = ", ".join(p.name for p in flat_tomls)
        logger.warning(
            "Found flat .toml files in %s: %s. Migrate to folder format: <name>/config.toml",
            directory,
            names,
        )

    include_set = set(include) if include is not None else None
    exclude_set = set(exclude) if exclude is not None else None

    base_config = load_base_config(directory)
    configs = []
    for d in sorted(directory.iterdir()):
        if not d.is_dir() or not (d / "config.toml").exists():
            continue
        if include_set is not None and d.name not in include_set:
            continue
        if exclude_set is not None and d.name in exclude_set:
            continue
        configs.append(load_automation(d, base_config=base_config))
    return configs
