from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic import BaseModel, field_validator

from ai_automations.channels.base import ChannelConfig

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
    working_directory: str
    schedule: str
    backend: str = "claude_cli"
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 900
    skip_permissions: bool = True
    max_turns: int = 10
    use_worktree: bool = False
    channels: list[ChannelConfig] = []

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

    @property
    def schedule_seconds(self) -> float:
        return parse_schedule(self.schedule)

    @property
    def cwd(self) -> Path:
        return Path(self.working_directory).expanduser().resolve()


def load_automation(path: Path) -> AutomationConfig:
    """Load a single automation config from a TOML file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return AutomationConfig(**data)


def discover_automations(directory: Path) -> list[AutomationConfig]:
    """Discover all .toml automation configs in a directory."""
    if not directory.is_dir():
        return []
    configs = []
    for p in sorted(directory.glob("*.toml")):
        configs.append(load_automation(p))
    return configs
