from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_automations.config import (
    AutomationConfig,
    discover_automations,
    load_automation,
    parse_schedule,
)


# --- parse_schedule ---


class TestParseSchedule:
    def test_seconds(self):
        assert parse_schedule("60s") == 60.0

    def test_minutes(self):
        assert parse_schedule("30m") == 1800.0

    def test_hours(self):
        assert parse_schedule("24h") == 86400.0

    def test_days(self):
        assert parse_schedule("7d") == 604800.0

    def test_fractional(self):
        assert parse_schedule("1.5h") == 5400.0

    def test_case_insensitive(self):
        assert parse_schedule("1H") == 3600.0

    def test_whitespace(self):
        assert parse_schedule("  30m  ") == 1800.0

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid schedule"):
            parse_schedule("forever")

    def test_no_unit_raises(self):
        with pytest.raises(ValueError):
            parse_schedule("100")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_schedule("")


# --- AutomationConfig ---


class TestAutomationConfig:
    def _minimal(self, **overrides) -> AutomationConfig:
        defaults = {
            "name": "test",
            "prompt": "do something",
            "working_directory": ".",
            "schedule": "1h",
        }
        return AutomationConfig(**(defaults | overrides))

    def test_defaults(self):
        cfg = self._minimal()
        assert cfg.backend == "claude_cli"
        assert cfg.model is None
        assert cfg.reasoning_effort is None
        assert cfg.timeout_seconds == 900
        assert cfg.skip_permissions is True
        assert cfg.max_turns == 10
        assert cfg.use_worktree is False
        assert cfg.channels == []

    def test_schedule_seconds(self):
        cfg = self._minimal(schedule="2h")
        assert cfg.schedule_seconds == 7200.0

    def test_cwd_resolves(self):
        cfg = self._minimal(working_directory="/tmp")
        assert cfg.cwd == Path("/tmp").resolve()

    def test_valid_backends(self):
        for b in ("claude_cli", "claude_sdk", "codex_cli", "openai_agents_sdk", "gemini_cli"):
            cfg = self._minimal(backend=b)
            assert cfg.backend == b

    def test_invalid_backend_raises(self):
        with pytest.raises(ValidationError, match="Unknown backend"):
            self._minimal(backend="gpt4_cli")

    def test_valid_reasoning_effort(self):
        for r in ("low", "medium", "high", "max"):
            cfg = self._minimal(reasoning_effort=r)
            assert cfg.reasoning_effort == r

    def test_invalid_reasoning_effort_raises(self):
        with pytest.raises(ValidationError, match="reasoning_effort"):
            self._minimal(reasoning_effort="ultra")

    def test_none_reasoning_effort_allowed(self):
        cfg = self._minimal(reasoning_effort=None)
        assert cfg.reasoning_effort is None

    def test_with_channels(self):
        cfg = self._minimal(
            channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}]
        )
        assert len(cfg.channels) == 1
        assert cfg.channels[0].type == "slack"


# --- load_automation / discover_automations ---


class TestLoadAutomation:
    def test_load(self, sample_toml: Path):
        cfg = load_automation(sample_toml)
        assert cfg.name == "scan"
        assert cfg.prompt == "Find bugs."
        assert cfg.backend == "claude_cli"
        assert cfg.schedule == "1h"

    def test_load_missing_field(self, automations_dir: Path):
        p = automations_dir / "bad.toml"
        p.write_text('name = "bad"\n', encoding="utf-8")
        with pytest.raises(ValidationError):
            load_automation(p)


class TestDiscoverAutomations:
    def test_discover(self, automations_dir: Path, sample_toml: Path):
        configs = discover_automations(automations_dir)
        assert len(configs) == 1
        assert configs[0].name == "scan"

    def test_empty_dir(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        assert discover_automations(d) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert discover_automations(tmp_path / "nope") == []

    def test_multiple_sorted(self, automations_dir: Path):
        for name in ("beta", "alpha"):
            p = automations_dir / f"{name}.toml"
            p.write_text(
                f'name = "{name}"\nprompt = "hi"\nworking_directory = "."\nschedule = "1h"\n',
                encoding="utf-8",
            )
        configs = discover_automations(automations_dir)
        assert [c.name for c in configs] == ["alpha", "beta"]
