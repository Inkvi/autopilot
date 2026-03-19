from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from autopilot.cli import app
from autopilot.models import BackendResult
from autopilot.results import save_result

runner = CliRunner()


def _write_automation(dir: Path, name: str, **overrides) -> Path:
    """Create a folder-based automation config."""
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
    auto_dir = dir / name
    auto_dir.mkdir(parents=True, exist_ok=True)
    (auto_dir / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return auto_dir


# --- list ---


class TestListCommand:
    def test_shows_automations(self, automations_dir: Path):
        _write_automation(automations_dir, "scan")
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "claude_cli" in result.output

    def test_empty_dir(self, automations_dir: Path):
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "No automations" in result.output

    def test_shows_last_run(self, automations_dir: Path, tmp_path: Path):
        _write_automation(automations_dir, "scan")
        result = runner.invoke(app, ["list", "--dir", str(automations_dir)])
        assert "never" in result.output


# --- init ---


class TestInitCommand:
    def test_creates_folder(self, automations_dir: Path):
        result = runner.invoke(app, ["init", "new-scan", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "Created" in result.output
        assert (automations_dir / "new-scan" / "config.toml").exists()
        assert (automations_dir / "new-scan" / "skills").is_dir()

    def test_template_is_valid_toml(self, automations_dir: Path):
        runner.invoke(app, ["init", "valid", "--dir", str(automations_dir)])
        from autopilot.config import load_automation

        cfg = load_automation(automations_dir / "valid")
        assert cfg.name == "valid"

    def test_refuses_existing(self, automations_dir: Path):
        _write_automation(automations_dir, "existing")
        result = runner.invoke(app, ["init", "existing", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "Already exists" in result.output

    def test_creates_dir_if_missing(self, tmp_path: Path):
        new_dir = tmp_path / "new_automations"
        result = runner.invoke(app, ["init", "first", "--dir", str(new_dir)])
        assert result.exit_code == 0
        assert (new_dir / "first" / "config.toml").exists()


# --- run ---


class TestRunCommand:
    def test_missing_automation(self, automations_dir: Path):
        result = runner.invoke(
            app, ["run", "nonexistent", "--dir", str(automations_dir), "--results-dir", "/tmp/r"]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_runs_automation(self, automations_dir: Path, tmp_path: Path):
        _write_automation(automations_dir, "scan")
        results_dir = tmp_path / "results"

        with patch("autopilot.cli.run_automation", new_callable=AsyncMock) as mock_run:
            result = runner.invoke(
                app,
                ["run", "scan", "--dir", str(automations_dir), "--results-dir", str(results_dir)],
            )

        assert result.exit_code == 0
        mock_run.assert_called_once()

    def test_dry_run(self, automations_dir: Path):
        _write_automation(automations_dir, "scan", prompt="Check {{date}}")
        result = runner.invoke(app, ["run", "scan", "--dir", str(automations_dir), "--dry-run"])
        assert result.exit_code == 0
        assert "Resolved prompt" in result.output
        assert "claude_cli" in result.output
        assert "{{date}}" not in result.output

    def test_dry_run_does_not_execute(self, automations_dir: Path):
        _write_automation(automations_dir, "scan")
        with patch("autopilot.cli.run_automation", new_callable=AsyncMock) as mock_run:
            result = runner.invoke(app, ["run", "scan", "--dir", str(automations_dir), "--dry-run"])
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

        with patch("autopilot.scheduler.daemon_loop", new_callable=AsyncMock) as mock_loop:
            result = runner.invoke(
                app,
                [
                    "daemon",
                    "--dir",
                    str(automations_dir),
                    "--results-dir",
                    str(results_dir),
                    "--poll-interval",
                    "30",
                    "--max-concurrency",
                    "3",
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
        _write_automation(automations_dir, "scan")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_missing_dir(self, tmp_path: Path):
        result = runner.invoke(app, ["validate", "--dir", str(tmp_path / "nope")])
        assert result.exit_code == 1

    def test_empty_dir(self, automations_dir: Path):
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "No automation folders" in result.output

    def test_invalid_config(self, automations_dir: Path):
        d = automations_dir / "bad"
        d.mkdir()
        (d / "config.toml").write_text('name = "bad"\n', encoding="utf-8")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1

    def test_bad_working_directory(self, automations_dir: Path):
        _write_automation(automations_dir, "scan", working_directory="/nonexistent/path/xyz")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 1
        assert "does not exist" in result.output

    def test_warns_on_flat_toml(self, automations_dir: Path):
        _write_automation(automations_dir, "scan")
        (automations_dir / "old.toml").write_text('name = "old"\n', encoding="utf-8")
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "flat .toml" in result.output.lower() or "migrate" in result.output.lower()

    def test_webhook_only_no_schedule(self, automations_dir: Path):
        d = automations_dir / "hook"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "hook"\nprompt = "hi"\nbackend = "claude_cli"\nwebhook_secret = "s"\n',
            encoding="utf-8",
        )
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0

    def test_warns_gh_not_in_path(self, automations_dir: Path):
        d = automations_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "hi"\nworking_directory = "."\nschedule = "1h"\n'
            '[[channels]]\ntype = "github_issue"\nrepo = "owner/repo"\n',
            encoding="utf-8",
        )
        with patch("shutil.which", return_value=None):
            result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "gh" in result.output.lower()

    def test_warns_skill_without_skill_md(self, automations_dir: Path):
        auto = _write_automation(automations_dir, "scan")
        skills = auto / "skills"
        skills.mkdir()
        (skills / "bad-skill").mkdir()
        result = runner.invoke(app, ["validate", "--dir", str(automations_dir)])
        assert result.exit_code == 0
        assert "no SKILL.md" in result.output


# --- costs ---


class TestCostsCommand:
    def test_no_results(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        result = runner.invoke(app, ["costs", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "No cost data" in result.output

    def test_shows_costs(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        t1 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 12, 0, 30, tzinfo=UTC)
        br = BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        from autopilot.models import TokenUsage

        save_result(
            results_dir,
            "scan",
            br,
            backend="claude_cli",
            model=None,
            usage=TokenUsage(tokens_in=1000, tokens_out=500, cost_usd=0.05),
        )

        result = runner.invoke(app, ["costs", "--results-dir", str(results_dir)])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "0.05" in result.output

    def test_filter_by_name(self, tmp_path: Path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        t1 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 1, 12, 0, 30, tzinfo=UTC)
        br = BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        from autopilot.models import TokenUsage

        save_result(
            results_dir,
            "scan",
            br,
            backend="claude_cli",
            model=None,
            usage=TokenUsage(tokens_in=100, tokens_out=50, cost_usd=0.01),
        )
        save_result(
            results_dir,
            "lint",
            br,
            backend="claude_cli",
            model=None,
            usage=TokenUsage(tokens_in=200, tokens_out=100, cost_usd=0.02),
        )

        result = runner.invoke(app, ["costs", "--results-dir", str(results_dir), "--name", "scan"])
        assert result.exit_code == 0
        assert "scan" in result.output

    def test_filter_by_since(self, tmp_path: Path):
        from datetime import timedelta

        results_dir = tmp_path / "results"
        results_dir.mkdir()
        now = datetime.now(UTC)
        t1 = now - timedelta(hours=1)
        t2 = now
        br = BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        from autopilot.models import TokenUsage

        save_result(
            results_dir,
            "scan",
            br,
            backend="claude_cli",
            model=None,
            usage=TokenUsage(tokens_in=100, tokens_out=50, cost_usd=0.01),
        )

        result = runner.invoke(app, ["costs", "--results-dir", str(results_dir), "--since", "7d"])
        assert result.exit_code == 0
        assert "scan" in result.output
        assert "0.01" in result.output


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
