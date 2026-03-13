from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from ai_automations.cli import app
from ai_automations.models import BackendResult
from ai_automations.results import save_result
from ai_automations.state import update_last_run

runner = CliRunner()


def _write_toml(dir: Path, name: str, **overrides) -> Path:
    defaults = {
        "prompt": "do things",
        "working_directory": ".",
        "schedule": "1h",
        "backend": "claude_cli",
    }
    fields = defaults | overrides
    lines = [f'name = "{name}"']
    for k, v in fields.items():
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, int):
            lines.append(f"{k} = {v}")
        else:
            lines.append(f'{k} = "{v}"')
    p = dir / f"{name}.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# --- list ---


class TestListCommand:
    def test_shows_automations(self, automations_dir: Path):
        _write_toml(automations_dir, "scan")
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "claude_cli" in result.output

    def test_empty_dir(self, automations_dir: Path):
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "No automations" in result.output

    def test_shows_last_run(self, automations_dir: Path, tmp_path: Path):
        _write_toml(automations_dir, "scan")
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert "never" in result.output


# --- init ---


class TestInitCommand:
    def test_creates_file(self, automations_dir: Path):
        result = runner.invoke(app, ["init", "new-scan", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (automations_dir / "new-scan.toml").exists()

    def test_template_is_valid_toml(self, automations_dir: Path):
        runner.invoke(app, ["init", "valid", "--dir", str(automations_dir)])
        from ai_automations.config import load_automation
        cfg = load_automation(automations_dir / "valid.toml")
        assert cfg.name == "valid"

    def test_refuses_existing(self, automations_dir: Path):
        _write_toml(automations_dir, "existing")
        result = runner.invoke(app, ["init", "existing", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "Already exists" in result.output

    def test_creates_dir_if_missing(self, tmp_path: Path):
        new_dir = tmp_path / "new_automations"
        result = runner.invoke(app, ["init", "first", "--dir", str(new_dir)])
        assert result.exit_code == 0
        assert (new_dir / "first.toml").exists()


# --- run ---


class TestRunCommand:
    def test_missing_automation(self, automations_dir: Path):
        result = runner.invoke(
            app, ["run", "nonexistent", "--dir", str(automations_dir), "--results-dir", "/tmp/r"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_runs_automation(self, automations_dir: Path, tmp_path: Path):
        _write_toml(automations_dir, "scan")
        results_dir = tmp_path / "results"

        with patch("ai_automations.cli.run_automation", new_callable=AsyncMock) as mock_run:
            result = runner.invoke(
                app,
                ["run", "scan", "--dir", str(automations_dir), "--results-dir", str(results_dir)],
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_dry_run(self, automations_dir: Path):
        _write_toml(automations_dir, "scan", prompt="Check {{date}}")
        result = runner.invoke(
            app, ["run", "scan", "--dir", str(automations_dir), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "Resolved prompt" in result.output
        assert "claude_cli" in result.output
        # Template should be resolved
        assert "{{date}}" not in result.output

    def test_dry_run_does_not_execute(self, automations_dir: Path):
        _write_toml(automations_dir, "scan")
        with patch("ai_automations.cli.run_automation", new_callable=AsyncMock) as mock_run:
            result = runner.invoke(
                app, ["run", "scan", "--dir", str(automations_dir), "--dry-run"]
            )
        assert result.exit_code == 0
        mock_run.assert_not_called()


# --- history ---


class TestHistoryCommand:
    def test_no_history(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        result = runner.invoke(app, ["history", "scan", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "No history" in result.output

    def test_shows_entries(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
        br = BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        save_result(results_dir, "scan", br, backend="claude_cli", model="sonnet")

        result = runner.invoke(app, ["history", "scan", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "ok" in result.output
        assert "claude_cli" in result.output

    def test_limit_option(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        result = runner.invoke(
            app, ["history", "scan", "--results-dir", str(results_dir), "--limit", "5"]
        )
        assert result.exit_code == 0


# --- daemon ---


class TestDaemonCommand:
    def test_daemon_invokes_loop(self, automations_dir: Path, tmp_path: Path):
        results_dir = tmp_path / "results"

        with patch("ai_automations.cli.daemon_loop", new_callable=AsyncMock) as mock_loop:
            result = runner.invoke(
                app,
                [
                    "daemon",
                    "--dir", str(automations_dir),
                    "--results-dir", str(results_dir),
                    "--poll-interval", "30",
                    "--max-concurrency", "3",
                ],
            )

        assert result.exit_code == 0
        mock_loop.assert_called_once()
        call_kwargs = mock_loop.call_args
        assert call_kwargs.kwargs["poll_interval"] == 30
        assert call_kwargs.kwargs["max_concurrency"] == 3


# --- validate ---


class TestValidateCommand:
    def test_valid_config(self, automations_dir: Path):
        _write_toml(automations_dir, "scan")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_missing_dir(self, tmp_path: Path):
        result = runner.invoke(app, ["validate", "--dir", str(tmp_path / "nope")])
        assert result.exit_code == 1

    def test_empty_dir(self, automations_dir: Path):
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "No .toml" in result.output

    def test_invalid_config(self, automations_dir: Path):
        (automations_dir / "bad.toml").write_text('name = "bad"\n', encoding="utf-8")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1

    def test_bad_working_directory(self, automations_dir: Path):
        _write_toml(automations_dir, "scan", working_directory="/nonexistent/path/xyz")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "does not exist" in result.output


# --- prune ---


class TestPruneCommand:
    def test_prune_nothing(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        result = runner.invoke(app, ["prune", "30d", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "Nothing" in result.output

    def test_prune_old_results(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        # Create a result with an old timestamp
        t1 = datetime(2020, 1, 1, tzinfo=UTC)
        t2 = datetime(2020, 1, 1, 0, 5, tzinfo=UTC)
        br = BackendResult(status="ok", output="old", error=None, started_at=t1, ended_at=t2)
        save_result(results_dir, "scan", br, backend="claude_cli", model=None)

        result = runner.invoke(app, ["prune", "1d", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "Pruned 1" in result.output

    def test_prune_invalid_duration(self, tmp_path: Path):
        result = runner.invoke(app, ["prune", "forever", "--results-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "Invalid" in result.output
