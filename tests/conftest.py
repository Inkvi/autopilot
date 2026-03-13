from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_automations.models import BackendResult


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def automations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "automations"
    d.mkdir()
    return d


@pytest.fixture()
def results_dir(tmp_path: Path) -> Path:
    d = tmp_path / "results"
    d.mkdir()
    return d


@pytest.fixture()
def sample_automation(automations_dir: Path) -> Path:
    d = automations_dir / "scan"
    d.mkdir()
    p = d / "config.toml"
    p.write_text(
        'name = "scan"\n'
        'prompt = "Find bugs."\n'
        'working_directory = "."\n'
        'schedule = "1h"\n'
        'backend = "claude_cli"\n',
        encoding="utf-8",
    )
    return d


@pytest.fixture()
def ok_result() -> BackendResult:
    t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
    return BackendResult(status="ok", output="All clear.", error=None, started_at=t1, ended_at=t2)


@pytest.fixture()
def error_result() -> BackendResult:
    t1 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC)
    return BackendResult(
        status="error", output="", error="CLI timed out", started_at=t1, ended_at=t2
    )
