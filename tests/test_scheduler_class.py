from __future__ import annotations

from pathlib import Path

import pytest

from autopilot.scheduler import Scheduler


class TestScheduler:
    def test_init(self, tmp_path: Path):
        s = Scheduler(
            automations_dir=tmp_path / "automations",
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        assert s.max_concurrency == 3
        assert len(s.running) == 0

    def test_is_running(self, tmp_path: Path):
        s = Scheduler(
            automations_dir=tmp_path / "automations",
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        assert s.is_running("foo") is False
        s.running.add("foo")
        assert s.is_running("foo") is True

    async def test_trigger_run_not_found(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir()
        s = Scheduler(
            automations_dir=auto_dir,
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        with pytest.raises(ValueError, match="not found"):
            await s.trigger_run("nonexistent")

    async def test_trigger_run_rejects_if_running(self, tmp_path: Path):
        s = Scheduler(
            automations_dir=tmp_path / "automations",
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        s.running.add("env-check")
        with pytest.raises(ValueError, match="already running"):
            await s.trigger_run("env-check")
