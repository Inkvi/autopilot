from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ai_automations.state import get_last_run, load_state, save_state, update_last_run


class TestLoadSaveState:
    def test_empty_when_no_file(self, tmp_path: Path):
        assert load_state(tmp_path) == {}

    def test_round_trip(self, tmp_path: Path):
        state = {"scan": "2026-01-01T12:00:00+00:00"}
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        assert loaded == state

    def test_creates_parent_dirs(self, tmp_path: Path):
        base = tmp_path / "nested" / "deep"
        save_state(base, {"x": "y"})
        assert load_state(base) == {"x": "y"}

    def test_corrupt_json_returns_empty(self, tmp_path: Path):
        state_dir = tmp_path / ".state"
        state_dir.mkdir(parents=True)
        (state_dir / "scheduler-state.json").write_text("{bad", encoding="utf-8")
        assert load_state(tmp_path) == {}


class TestGetLastRun:
    def test_none_when_never_run(self, tmp_path: Path):
        assert get_last_run(tmp_path, "scan") is None

    def test_returns_datetime(self, tmp_path: Path):
        ts = "2026-03-12T10:00:00+00:00"
        save_state(tmp_path, {"scan": ts})
        result = get_last_run(tmp_path, "scan")
        assert result is not None
        assert result.year == 2026
        assert result.month == 3

    def test_unknown_name_returns_none(self, tmp_path: Path):
        save_state(tmp_path, {"scan": "2026-01-01T00:00:00+00:00"})
        assert get_last_run(tmp_path, "other") is None


class TestUpdateLastRun:
    def test_updates(self, tmp_path: Path):
        t = datetime(2026, 6, 15, 8, 0, 0, tzinfo=UTC)
        update_last_run(tmp_path, "scan", t)
        assert get_last_run(tmp_path, "scan") == t

    def test_preserves_other_entries(self, tmp_path: Path):
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 1, tzinfo=UTC)
        update_last_run(tmp_path, "a", t1)
        update_last_run(tmp_path, "b", t2)
        assert get_last_run(tmp_path, "a") == t1
        assert get_last_run(tmp_path, "b") == t2

    def test_defaults_to_now(self, tmp_path: Path):
        update_last_run(tmp_path, "scan")
        result = get_last_run(tmp_path, "scan")
        assert result is not None
        assert result.year >= 2026
