from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from autopilot.config import (
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
        assert cfg.channels == []
        assert cfg.source_dir is None
        assert cfg.copy_files == [".env", ".env.local", ".envrc"]

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

    def test_custom_copy_files(self):
        cfg = self._minimal(copy_files=[".env", ".secrets/keys"])
        assert cfg.copy_files == [".env", ".secrets/keys"]

    def test_copy_files_rejects_parent_traversal(self):
        with pytest.raises(ValidationError, match="outside working directory"):
            self._minimal(copy_files=["../../etc/passwd"])

    def test_copy_files_rejects_absolute_paths(self):
        with pytest.raises(ValidationError, match="must be relative"):
            self._minimal(copy_files=["/etc/passwd"])


# --- load_automation / discover_automations ---


class TestLoadAutomation:
    def test_load_from_directory(self, sample_automation: Path):
        cfg = load_automation(sample_automation)
        assert cfg.name == "scan"
        assert cfg.prompt == "Find bugs."
        assert cfg.backend == "claude_cli"
        assert cfg.schedule == "1h"
        assert cfg.source_dir == sample_automation

    def test_load_missing_config_toml(self, automations_dir: Path):
        d = automations_dir / "empty"
        d.mkdir()
        with pytest.raises(FileNotFoundError):
            load_automation(d)

    def test_load_missing_field(self, automations_dir: Path):
        d = automations_dir / "bad"
        d.mkdir()
        (d / "config.toml").write_text('name = "bad"\n', encoding="utf-8")
        with pytest.raises(ValidationError):
            load_automation(d)


class TestDiscoverAutomations:
    def test_discover(self, automations_dir: Path, sample_automation: Path):
        configs = discover_automations(automations_dir)
        assert len(configs) == 1
        assert configs[0].name == "scan"
        assert configs[0].source_dir == sample_automation

    def test_empty_dir(self, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        assert discover_automations(d) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert discover_automations(tmp_path / "nope") == []

    def test_multiple_sorted(self, automations_dir: Path):
        for name in ("beta", "alpha"):
            d = automations_dir / name
            d.mkdir()
            (d / "config.toml").write_text(
                f'name = "{name}"\nprompt = "hi"\nworking_directory = "."\nschedule = "1h"\n',
                encoding="utf-8",
            )
        configs = discover_automations(automations_dir)
        assert [c.name for c in configs] == ["alpha", "beta"]

    def test_warns_on_flat_toml(self, automations_dir: Path, sample_automation: Path, caplog):
        (automations_dir / "old.toml").write_text('name = "old"\n', encoding="utf-8")
        with caplog.at_level(logging.WARNING):
            configs = discover_automations(automations_dir)
        assert len(configs) == 1
        assert "old.toml" in caplog.text
