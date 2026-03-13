from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_automations.config import AutomationConfig
from ai_automations.models import BackendResult
from ai_automations.scheduler import _is_due, run_automation
from ai_automations.state import update_last_run


def _make_config(**overrides) -> AutomationConfig:
    defaults = {
        "name": "test-auto",
        "prompt": "scan for bugs",
        "working_directory": ".",
        "schedule": "1h",
        "backend": "claude_cli",
    }
    return AutomationConfig(**(defaults | overrides))


# --- _is_due ---


class TestIsDue:
    def test_never_run_is_due(self, tmp_path: Path):
        cfg = _make_config()
        assert _is_due(cfg, tmp_path) is True

    def test_recently_run_not_due(self, tmp_path: Path):
        cfg = _make_config(schedule="1h")
        update_last_run(tmp_path, cfg.name, datetime.now(UTC))
        assert _is_due(cfg, tmp_path) is False

    def test_past_schedule_is_due(self, tmp_path: Path):
        cfg = _make_config(schedule="1h")
        old = datetime.now(UTC) - timedelta(hours=2)
        update_last_run(tmp_path, cfg.name, old)
        assert _is_due(cfg, tmp_path) is True

    def test_exact_boundary(self, tmp_path: Path):
        cfg = _make_config(schedule="60s")
        old = datetime.now(UTC) - timedelta(seconds=61)
        update_last_run(tmp_path, cfg.name, old)
        assert _is_due(cfg, tmp_path) is True


# --- run_automation ---


class TestRunAutomation:
    def _fake_result(self) -> BackendResult:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        return BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)

    async def test_runs_and_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        with patch("ai_automations.scheduler.get_backend", return_value=fake_backend):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_backend.run.assert_called_once()
        # Check result was saved
        assert (results_dir / "test-auto").is_dir()
        assert len(list((results_dir / "test-auto").glob("*.meta.json"))) == 1

    async def test_updates_state(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        with patch("ai_automations.scheduler.get_backend", return_value=fake_backend):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        from ai_automations.state import get_last_run
        assert get_last_run(tmp_path, "test-auto") is not None

    async def test_error_result_still_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        t = datetime(2026, 1, 1, tzinfo=UTC)
        err_result = BackendResult(status="error", output="", error="boom", started_at=t, ended_at=t)
        fake_backend = AsyncMock()
        fake_backend.run.return_value = err_result

        with patch("ai_automations.scheduler.get_backend", return_value=fake_backend):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        meta_files = list((results_dir / "test-auto").glob("*.meta.json"))
        assert len(meta_files) == 1

    async def test_notifies_channels(self, tmp_path: Path):
        cfg = _make_config(
            channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}]
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()
        fake_channel = AsyncMock()

        with (
            patch("ai_automations.scheduler.get_backend", return_value=fake_backend),
            patch("ai_automations.scheduler.get_channel", return_value=fake_channel),
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_channel.notify.assert_called_once()

    async def test_channel_error_does_not_crash(self, tmp_path: Path):
        cfg = _make_config(
            channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}]
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()
        fake_channel = AsyncMock()
        fake_channel.notify.side_effect = RuntimeError("webhook down")

        with (
            patch("ai_automations.scheduler.get_backend", return_value=fake_backend),
            patch("ai_automations.scheduler.get_channel", return_value=fake_channel),
        ):
            # Should not raise
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

    async def test_worktree_path(self, tmp_path: Path):
        cfg = _make_config(use_worktree=True)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_result = self._fake_result()

        with patch("ai_automations.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = fake_result
            with patch("ai_automations.scheduler.get_backend"):
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_wt.assert_called_once()
