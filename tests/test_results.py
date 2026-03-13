from __future__ import annotations

import json
from pathlib import Path

from ai_automations.models import BackendResult
from ai_automations.results import load_history, prune_results, save_result


class TestSaveResult:
    def test_creates_files(self, results_dir: Path, ok_result: BackendResult):
        out = save_result(results_dir, "scan", ok_result, backend="claude_cli", model=None)
        md_files = list(out.glob("*.md"))
        meta_files = list(out.glob("*.meta.json"))
        assert len(md_files) == 1
        assert len(meta_files) == 1

    def test_output_content(self, results_dir: Path, ok_result: BackendResult):
        save_result(results_dir, "scan", ok_result, backend="claude_cli", model=None)
        md_file = next((results_dir / "scan").glob("*.md"))
        assert md_file.read_text(encoding="utf-8") == "All clear."

    def test_meta_content(self, results_dir: Path, ok_result: BackendResult):
        save_result(results_dir, "scan", ok_result, backend="claude_cli", model="sonnet")
        meta_file = next((results_dir / "scan").glob("*.meta.json"))
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["status"] == "ok"
        assert meta["backend"] == "claude_cli"
        assert meta["model"] == "sonnet"
        assert meta["duration_s"] == 30.0
        assert meta["error"] is None

    def test_error_result(self, results_dir: Path, error_result: BackendResult):
        save_result(results_dir, "scan", error_result, backend="codex_cli", model=None)
        meta_file = next((results_dir / "scan").glob("*.meta.json"))
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["status"] == "error"
        assert meta["error"] == "CLI timed out"

    def test_returns_directory(self, results_dir: Path, ok_result: BackendResult):
        out = save_result(results_dir, "scan", ok_result, backend="claude_cli", model=None)
        assert out == results_dir / "scan"
        assert out.is_dir()


class TestLoadHistory:
    def test_empty_when_no_results(self, results_dir: Path):
        assert load_history(results_dir, "scan") == []

    def test_loads_entries(self, results_dir: Path, ok_result: BackendResult):
        save_result(results_dir, "scan", ok_result, backend="claude_cli", model=None)
        entries = load_history(results_dir, "scan")
        assert len(entries) == 1
        assert entries[0]["status"] == "ok"

    def test_sorted_descending(self, results_dir: Path):
        from datetime import UTC, datetime
        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 1, 1, 10, 0, 30, tzinfo=UTC)
        t3 = datetime(2026, 1, 2, 10, 0, 0, tzinfo=UTC)
        t4 = datetime(2026, 1, 2, 10, 0, 15, tzinfo=UTC)
        r1 = BackendResult(status="ok", output="first", error=None, started_at=t1, ended_at=t2)
        r2 = BackendResult(status="error", output="", error="fail", started_at=t3, ended_at=t4)
        save_result(results_dir, "scan", r1, backend="claude_cli", model=None)
        save_result(results_dir, "scan", r2, backend="claude_cli", model=None)
        entries = load_history(results_dir, "scan")
        assert len(entries) == 2
        # Second run (later date) should sort first (descending)
        assert entries[0]["status"] == "error"
        assert entries[1]["status"] == "ok"

    def test_skips_corrupt_meta(self, results_dir: Path, ok_result: BackendResult):
        save_result(results_dir, "scan", ok_result, backend="claude_cli", model=None)
        # Write a corrupt meta file
        (results_dir / "scan" / "corrupt.meta.json").write_text("{bad", encoding="utf-8")
        entries = load_history(results_dir, "scan")
        assert len(entries) == 1  # only the valid one


class TestPruneResults:
    def test_prune_old(self, results_dir: Path):
        from datetime import UTC, datetime
        t1 = datetime(2020, 1, 1, tzinfo=UTC)
        t2 = datetime(2020, 1, 1, 0, 5, tzinfo=UTC)
        br = BackendResult(status="ok", output="old", error=None, started_at=t1, ended_at=t2)
        save_result(results_dir, "scan", br, backend="claude_cli", model=None)

        removed = prune_results(results_dir, 86400)  # older than 1 day
        assert removed == 1
        assert load_history(results_dir, "scan") == []

    def test_prune_keeps_recent(self, results_dir: Path):
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        br = BackendResult(
            status="ok", output="recent", error=None, started_at=now, ended_at=now,
        )
        save_result(results_dir, "scan", br, backend="claude_cli", model=None)
        removed = prune_results(results_dir, 86400)
        assert removed == 0
        assert len(load_history(results_dir, "scan")) == 1

    def test_prune_empty_dir(self, results_dir: Path):
        assert prune_results(results_dir, 86400) == 0

    def test_prune_nonexistent_dir(self, tmp_path: Path):
        assert prune_results(tmp_path / "nope", 86400) == 0
