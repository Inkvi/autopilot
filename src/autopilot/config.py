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


class TriggerConfig(BaseModel):
    trigger: list[str] = []


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
    skills: list[str] = []
    on_success: TriggerConfig | None = None
    on_error: TriggerConfig | None = None
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

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, v: list[str]) -> list[str]:
        from autopilot.repos import parse_github_tree_url

        for url in v:
            parse_github_tree_url(url)  # raises ValueError if invalid
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


def validate_trigger_graph(configs: list[AutomationConfig]) -> list[str]:
    """Validate trigger targets exist and detect circular dependencies.

    Returns a list of error messages (empty means valid).
    """
    errors: list[str] = []
    names = {c.name for c in configs}

    # Build adjacency list and check for missing targets
    graph: dict[str, list[str]] = {}
    for c in configs:
        targets: list[str] = []
        for section_label, section in [("on_success", c.on_success), ("on_error", c.on_error)]:
            if section is None:
                continue
            for t in section.trigger:
                if t not in names:
                    errors.append(f"{c.name}: {section_label} trigger target '{t}' not found")
                targets.append(t)
        graph[c.name] = targets

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {name: WHITE for name in names}
    path: list[str] = []

    def _dfs(node: str) -> None:
        if node not in color:
            return
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                errors.append(f"Circular trigger dependency: {' -> '.join(cycle)}")
            elif color[neighbor] == WHITE:
                _dfs(neighbor)
        path.pop()
        color[node] = BLACK

    for name in sorted(names):
        if color[name] == WHITE:
            _dfs(name)

    return errors


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
