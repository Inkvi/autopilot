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

    def test_no_schedule_never_due(self, tmp_path: Path):
        cfg = _make_config(schedule=None, webhook_secret="s")
        assert _is_due(cfg, tmp_path) is False

    def test_once_never_run_is_due(self, tmp_path: Path):
        cfg = _make_config(once=True, schedule=None, webhook_secret="s")
        assert _is_due(cfg, tmp_path) is True

    def test_once_already_run_not_due(self, tmp_path: Path):
        cfg = _make_config(once=True, schedule=None, webhook_secret="s")
        update_last_run(tmp_path, cfg.name, datetime.now(UTC))
        assert _is_due(cfg, tmp_path) is False


# --- run_automation ---


class TestRunAutomation:
    def _fake_result(self, status="ok") -> BackendResult:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        if status == "ok":
            return BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        return BackendResult(status="error", output="", error="boom", started_at=t1, ended_at=t2)

    def _wt_patches(self):
        """Return context managers for worktree + backend mocking."""
        mock_create = patch(
            "autopilot.scheduler.create_worktree",
            new_callable=AsyncMock,
            return_value=(Path("/tmp/fake-wt"), "fake-branch"),
        )
        mock_cleanup = patch("autopilot.scheduler.cleanup_worktree", new_callable=AsyncMock)
        mock_backend = patch("autopilot.scheduler.get_backend")
        return mock_create, mock_cleanup, mock_backend

    async def test_runs_and_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert (results_dir / "test-auto").is_dir()
        assert len(list((results_dir / "test-auto").glob("*.meta.json"))) == 1

    async def test_updates_state(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        from autopilot.state import get_last_run

        assert get_last_run(tmp_path, "test-auto") is not None

    async def test_error_result_still_saves(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result("error")
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        meta_files = list((results_dir / "test-auto").glob("*.meta.json"))
        assert len(meta_files) == 1

    async def test_notifies_channels(self, tmp_path: Path):
        cfg = _make_config(channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}])
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_channel = AsyncMock()
        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            mock_get_backend as mgb,
            patch("autopilot.scheduler.get_channel", return_value=fake_channel),
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_channel.notify.assert_called_once()
        call_kwargs = fake_channel.notify.call_args.kwargs
        assert "context" in call_kwargs
        assert "worktree_path" in call_kwargs["context"]

    async def test_channel_error_does_not_crash(self, tmp_path: Path):
        cfg = _make_config(channels=[{"type": "slack", "webhook_url": "https://example.com/hook"}])
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        fake_channel = AsyncMock()
        fake_channel.notify.side_effect = RuntimeError("webhook down")
        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            mock_get_backend as mgb,
            patch("autopilot.scheduler.get_channel", return_value=fake_channel),
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

    async def test_resolves_prompt_templates(self, tmp_path: Path):
        cfg = _make_config(prompt="Run on {{date}}")
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        actual_prompt = fake_backend.run.call_args[0][0]
        assert "{{date}}" not in actual_prompt
        assert "Run on 20" in actual_prompt

    async def test_retry_on_failure(self, tmp_path: Path):
        cfg = _make_config(max_retries=2)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.side_effect = [
                self._fake_result("error"),
                self._fake_result("error"),
                self._fake_result("ok"),
            ]
            mgb.return_value = fake_backend
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert fake_backend.run.call_count == 3

    async def test_retry_exhausted_saves_last_error(self, tmp_path: Path):
        cfg = _make_config(max_retries=1)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result("error")
            mgb.return_value = fake_backend
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert fake_backend.run.call_count == 2
        assert len(list((results_dir / "test-auto").glob("*.meta.json"))) == 1

    async def test_no_retry_when_zero(self, tmp_path: Path):
        cfg = _make_config(max_retries=0)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with mock_create, mock_cleanup, mock_get_backend as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result("error")
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert fake_backend.run.call_count == 1

    async def test_cleanup_runs_even_on_error(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create_cm = patch(
            "autopilot.scheduler.create_worktree",
            new_callable=AsyncMock,
            return_value=(Path("/tmp/fake-wt"), "fake-branch"),
        )
        mock_cleanup_cm = patch("autopilot.scheduler.cleanup_worktree", new_callable=AsyncMock)
        mock_get_backend_cm = patch("autopilot.scheduler.get_backend")

        with mock_create_cm, mock_cleanup_cm as mock_cleanup, mock_get_backend_cm as mgb:
            fake_backend = AsyncMock()
            fake_backend.run.side_effect = RuntimeError("backend crashed")
            mgb.return_value = fake_backend
            try:
                await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)
            except RuntimeError:
                pass

        mock_cleanup.assert_called_once()

    async def test_worktree_create_failure(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with patch(
            "autopilot.scheduler.create_worktree",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        meta_files = list((results_dir / "test-auto").glob("*.meta.json"))
        assert len(meta_files) == 1
        import json

        meta = json.loads(meta_files[0].read_text())
        assert meta["status"] == "error"

    async def test_last_run_not_updated_on_failure(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            mock_get_backend as mgb,
            patch("autopilot.scheduler.update_last_run") as mock_update,
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result("error")
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_update.assert_not_called()

    async def test_last_run_updated_on_success(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            mock_get_backend as mgb,
            patch("autopilot.scheduler.update_last_run") as mock_update,
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result("ok")
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_update.assert_called_once()

    def _ok_backend(self):
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result("ok")
        return fake_backend

    async def test_remote_skills_fetched_and_injected(self, tmp_path):
        """Remote skills are fetched and injected into the worktree."""
        cfg = _make_config(skills=["https://github.com/org/repo/tree/main/skills/foo"])
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_create, mock_cleanup, mock_get_backend = self._wt_patches()
        mock_fetch = patch(
            "autopilot.scheduler.fetch_remote_skills",
            new_callable=AsyncMock,
            return_value=[Path("/fake/skills/foo")],
        )
        mock_inject = patch("autopilot.scheduler.inject_skill_paths")

        with (
            mock_create,
            mock_cleanup,
            mock_get_backend as mgb,
            mock_fetch as mf,
            mock_inject as mi,
        ):
            mgb.return_value = self._ok_backend()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mf.assert_called_once_with(["https://github.com/org/repo/tree/main/skills/foo"], tmp_path)
        mi.assert_called_once()

    async def test_fallback_to_second_backend(self, tmp_path: Path):
        """When the first backend fails, the second backend is tried and its name is recorded."""
        cfg = _make_config(backend=["claude_cli", "gemini_cli"])
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        first_backend = AsyncMock()
        first_backend.run.return_value = self._fake_result("error")
        second_backend = AsyncMock()
        second_backend.run.return_value = self._fake_result("ok")

        mock_create, mock_cleanup, _ = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            patch(
                "autopilot.scheduler.get_backend",
                side_effect=[first_backend, second_backend],
            ),
            patch("autopilot.scheduler.save_result") as mock_save,
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        first_backend.run.assert_called_once()
        second_backend.run.assert_called_once()
        # The saved result should record "gemini_cli" as the backend
        assert mock_save.call_args.kwargs["backend"] == "gemini_cli"

    async def test_fallback_uses_backend_specific_models(self, tmp_path: Path):
        cfg = _make_config(
            backend=["claude_cli", "gemini_cli"],
            model={
                "claude_cli": "claude-sonnet-4-5",
                "gemini_cli": "gemini-2.5-pro",
            },
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        first_backend = AsyncMock()
        first_backend.run.return_value = self._fake_result("error")
        second_backend = AsyncMock()
        second_backend.run.return_value = self._fake_result("ok")

        mock_create, mock_cleanup, _ = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            patch(
                "autopilot.scheduler.get_backend",
                side_effect=[first_backend, second_backend],
            ),
            patch("autopilot.scheduler.save_result") as mock_save,
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert first_backend.run.call_args.kwargs["model"] == "claude-sonnet-4-5"
        assert second_backend.run.call_args.kwargs["model"] == "gemini-2.5-pro"
        assert mock_save.call_args.kwargs["model"] == "gemini-2.5-pro"

    async def test_fallback_does_not_reuse_primary_model_for_other_backends(self, tmp_path: Path):
        cfg = _make_config(backend=["claude_cli", "gemini_cli"], model="claude-sonnet-4-5")
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        first_backend = AsyncMock()
        first_backend.run.return_value = self._fake_result("error")
        second_backend = AsyncMock()
        second_backend.run.return_value = self._fake_result("ok")

        mock_create, mock_cleanup, _ = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            patch(
                "autopilot.scheduler.get_backend",
                side_effect=[first_backend, second_backend],
            ),
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        assert first_backend.run.call_args.kwargs["model"] == "claude-sonnet-4-5"
        assert second_backend.run.call_args.kwargs["model"] is None

    async def test_fallback_retries_per_backend(self, tmp_path: Path):
        """Each backend gets 1 + max_retries attempts before falling through."""
        cfg = _make_config(backend=["claude_cli", "gemini_cli"], max_retries=1)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        first_backend = AsyncMock()
        first_backend.run.return_value = self._fake_result("error")
        second_backend = AsyncMock()
        second_backend.run.return_value = self._fake_result("ok")

        mock_create, mock_cleanup, _ = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            patch(
                "autopilot.scheduler.get_backend",
                side_effect=[first_backend, second_backend],
            ),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        # First backend: 1 initial + 1 retry = 2 calls
        assert first_backend.run.call_count == 2
        second_backend.run.assert_called_once()

    async def test_all_backends_exhausted(self, tmp_path: Path):
        """When all backends fail, the last error result is saved."""
        cfg = _make_config(backend=["claude_cli", "gemini_cli"], max_retries=0)
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        first_backend = AsyncMock()
        first_backend.run.return_value = self._fake_result("error")
        second_backend = AsyncMock()
        second_backend.run.return_value = self._fake_result("error")

        mock_create, mock_cleanup, _ = self._wt_patches()
        with (
            mock_create,
            mock_cleanup,
            patch(
                "autopilot.scheduler.get_backend",
                side_effect=[first_backend, second_backend],
            ),
            patch("autopilot.scheduler.save_result") as mock_save,
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        first_backend.run.assert_called_once()
        second_backend.run.assert_called_once()
        saved_result = mock_save.call_args[0][2]
        assert saved_result.status == "error"
        assert mock_save.call_args.kwargs["backend"] == "gemini_cli"

    async def test_remote_skills_injected_in_temp_dir(self, tmp_path):
        """Remote skills work when working_directory is None (temp dir path)."""
        cfg = _make_config(
            working_directory=None,
            skills=["https://github.com/org/repo/tree/main/skills/foo"],
        )
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        mock_fetch = patch(
            "autopilot.scheduler.fetch_remote_skills",
            new_callable=AsyncMock,
            return_value=[Path("/fake/skills/foo")],
        )
        mock_inject = patch("autopilot.scheduler.inject_skill_paths")
        mock_get_backend = patch("autopilot.scheduler.get_backend")

        with mock_fetch as mf, mock_inject as mi, mock_get_backend as mgb:
            mgb.return_value = self._ok_backend()
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mf.assert_called_once()
        mi.assert_called_once()


class TestConditionalExecution:
    def _fake_result(self, status="ok") -> BackendResult:
        t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC)
        if status == "ok":
            return BackendResult(status="ok", output="done", error=None, started_at=t1, ended_at=t2)
        return BackendResult(status="error", output="", error="boom", started_at=t1, ended_at=t2)

    async def test_skips_when_condition_false(self, tmp_path: Path):
        cfg = _make_config(run_if={"type": "command", "cmd": "false"})
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with (
            patch(
                "autopilot.scheduler.check_condition", new_callable=AsyncMock, return_value=False
            ) as mock_cond,
            patch("autopilot.scheduler.create_worktree", new_callable=AsyncMock) as mock_create,
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        mock_cond.assert_called_once()
        mock_create.assert_not_called()

    async def test_runs_when_condition_true(self, tmp_path: Path):
        cfg = _make_config(run_if={"type": "git_changes"})
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with (
            patch("autopilot.scheduler.check_condition", new_callable=AsyncMock, return_value=True),
            patch(
                "autopilot.scheduler.create_worktree",
                new_callable=AsyncMock,
                return_value=(Path("/tmp/fake-wt"), "fake-branch"),
            ),
            patch("autopilot.scheduler.cleanup_worktree", new_callable=AsyncMock),
            patch("autopilot.scheduler.get_backend") as mgb,
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_backend.run.assert_called_once()

    async def test_no_condition_always_runs(self, tmp_path: Path):
        cfg = _make_config()
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with (
            patch(
                "autopilot.scheduler.create_worktree",
                new_callable=AsyncMock,
                return_value=(Path("/tmp/fake-wt"), "fake-branch"),
            ),
            patch("autopilot.scheduler.cleanup_worktree", new_callable=AsyncMock),
            patch("autopilot.scheduler.get_backend") as mgb,
        ):
            fake_backend = AsyncMock()
            fake_backend.run.return_value = self._fake_result()
            mgb.return_value = fake_backend
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        fake_backend.run.assert_called_once()

    async def test_skipped_run_does_not_update_state(self, tmp_path: Path):
        cfg = _make_config(run_if={"type": "command", "cmd": "false"})
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        with (
            patch(
                "autopilot.scheduler.check_condition", new_callable=AsyncMock, return_value=False
            ),
            patch("autopilot.scheduler.create_worktree", new_callable=AsyncMock),
        ):
            await run_automation(cfg, base_dir=tmp_path, results_dir=results_dir)

        from autopilot.state import get_last_run

        assert get_last_run(tmp_path, cfg.name) is None
