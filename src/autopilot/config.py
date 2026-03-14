from __future__ import annotations

import logging
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

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


def parse_schedule(value: str) -> float:
    """Parse a human duration like '24h', '30m', '1d' into seconds."""
    m = _DURATION_RE.match(value.strip())
    if not m:
        raise ValueError(f"Invalid schedule duration: {value!r}. Use e.g. '30m', '1h', '24h'.")
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()]


class AutomationConfig(BaseModel):
    name: str
    prompt: str
    working_directory: str | None = None
    repos: list[str] = []
    schedule: str
    backend: str = "claude_cli"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 900
    skip_permissions: bool = True
    max_turns: int = 10
    max_retries: int = 0
    run_if: RunCondition | None = None
    channels: list[ChannelConfig] = []
    copy_files: list[str] = [".env", ".env.local", ".envrc"]
    source_dir: Path | None = None

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        allowed = {"claude_cli", "claude_sdk", "codex_cli", "openai_agents_sdk", "gemini_cli"}
        if v not in allowed:
            raise ValueError(f"Unknown backend {v!r}. Choose from: {', '.join(sorted(allowed))}")
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

    @property
    def schedule_seconds(self) -> float:
        return parse_schedule(self.schedule)

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


def discover_automations(directory: Path) -> list[AutomationConfig]:
    """Discover all folder-based automation configs in a directory."""
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

    base_config = load_base_config(directory)
    configs = []
    for d in sorted(directory.iterdir()):
        if d.is_dir() and (d / "config.toml").exists():
            configs.append(load_automation(d, base_config=base_config))
    return configs
