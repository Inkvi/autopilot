from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from autopilot.config import AutomationConfig
from autopilot.models import BackendResult
from autopilot.scheduler import _is_due, run_automation
from autopilot.state import update_last_run


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
    def _fake_result(self, status="ok") -> BackendResult:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        if status == "ok":
            return BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        return BackendResult(status="error", output="", error="boom", started_at=t1, ended_at=t2)

    async def test_always_uses_worktree(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_wt.assert_called_once()
        call_kwargs = mock_wt.call_args.kwargs
        assert "copy_files" in call_kwargs
        assert "skills_dir" in call_kwargs

    async def test_runs_and_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_wt.assert_called_once()
        assert (results_dir / "test-auto").is_dir()
        assert len(list((results_dir / "test-auto").glob("*.meta.json"))) == 1

    async def test_updates_state(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        from autopilot.state import get_last_run
        assert get_last_run(tmp_path, "test-auto") is not None

    async def test_error_result_still_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result("error")
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        meta_files = list((results_dir / "test-auto").glob("*.meta.json"))
        assert len(meta_files) == 1

    async def test_notifies_channels(self, tmp_path: Path):
        cfg = _make_config(
            channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}]
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_channel = AsyncMock()

        with (
            patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt,
            patch("autopilot.scheduler.get_channel", return_value=fake_channel),
        ):
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_channel.notify.assert_called_once()

    async def test_channel_error_does_not_crash(self, tmp_path: Path):
        cfg = _make_config(
            channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}]
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_channel = AsyncMock()
        fake_channel.notify.side_effect = RuntimeError("webhook down")

        with (
            patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt,
            patch("autopilot.scheduler.get_channel", return_value=fake_channel),
        ):
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

    async def test_resolves_prompt_templates(self, tmp_path: Path):
        cfg = _make_config(prompt="Run on {{date}}")
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        actual_prompt = mock_wt.call_args.kwargs["prompt"]
        assert "{{date}}" not in actual_prompt
        assert "Run on 20" in actual_prompt

    async def test_retry_on_failure(self, tmp_path: Path):
        cfg = _make_config(max_retries=2)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.side_effect = [
                self._fake_result("error"),
                self._fake_result("error"),
                self._fake_result("ok"),
            ]
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert mock_wt.call_count == 3

    async def test_retry_exhausted_saves_last_error(self, tmp_path: Path):
        cfg = _make_config(max_retries=1)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result("error")
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert mock_wt.call_count == 2
        assert len(list((results_dir / "test-auto").glob("*.meta.json"))) == 1

    async def test_no_retry_when_zero(self, tmp_path: Path):
        cfg = _make_config(max_retries=0)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch("autopilot.scheduler.run_with_worktree", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = self._fake_result("error")
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert mock_wt.call_count == 1
