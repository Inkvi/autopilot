from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from autopilot.api.app import create_app
from autopilot.models import BackendResult
from autopilot.results import save_result
from autopilot.scheduler import Scheduler


def _make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    auto_dir = tmp_path / "automations"
    auto_dir.mkdir()
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    scheduler = Scheduler(
        automations_dir=auto_dir,
        base_dir=tmp_path,
        results_dir=results_dir,
        max_concurrency=3,
    )
    app = create_app(scheduler)
    client = TestClient(app).__enter__()
    return client, results_dir


class TestListResults:
    def test_empty(self, tmp_path: Path):
        client, _ = _make_client(tmp_path)
        resp = client.get("/api/results/nonexistent")
        assert resp.status_code == 200
        assert resp.json()["runs"] == []

    def test_returns_history(self, tmp_path: Path):
        client, results_dir = _make_client(tmp_path)
        result = BackendResult(
            status="ok",
            output="# Done\nAll good.",
            error=None,
            started_at=datetime(2026, 3, 13, 14, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 3, 13, 14, 0, 13, tzinfo=UTC),
        )
        save_result(results_dir, "scan", result, backend="claude_cli", model="claude-sonnet-4-6")

        resp = client.get("/api/results/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["automation"] == "scan"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["status"] == "ok"
        assert data["runs"][0]["error"] is None

    def test_limit_param(self, tmp_path: Path):
        client, results_dir = _make_client(tmp_path)
        for i in range(5):
            result = BackendResult(
                status="ok",
                output=f"Run {i}",
                error=None,
                started_at=datetime(2026, 3, 13, i, 0, 0, tzinfo=UTC),
                ended_at=datetime(2026, 3, 13, i, 0, 10, tzinfo=UTC),
            )
            save_result(results_dir, "scan", result, backend="claude_cli", model=None)

        resp = client.get("/api/results/scan?limit=2")
        assert len(resp.json()["runs"]) == 2


class TestGetResult:
    def test_not_found(self, tmp_path: Path):
        client, _ = _make_client(tmp_path)
        resp = client.get("/api/results/scan/2026-03-13T140000Z")
        assert resp.status_code == 404

    def test_returns_detail(self, tmp_path: Path):
        client, results_dir = _make_client(tmp_path)
        result = BackendResult(
            status="ok",
            output="# Environment Check\nAll good.",
            error=None,
            started_at=datetime(2026, 3, 13, 14, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 3, 13, 14, 0, 13, tzinfo=UTC),
        )
        save_result(results_dir, "scan", result, backend="claude_cli", model="claude-sonnet-4-6")

        # Find the timestamp from saved files
        meta_files = list((results_dir / "scan").glob("*.meta.json"))
        ts = meta_files[0].name.replace(".meta.json", "")

        resp = client.get(f"/api/results/scan/{ts}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["status"] == "ok"
        assert "# Environment Check" in data["output"]
        assert data["has_conversation"] is False

    def test_returns_detail_with_conversation(self, tmp_path: Path):
        client, results_dir = _make_client(tmp_path)
        result = BackendResult(
            status="ok",
            output="Done",
            error=None,
            started_at=datetime(2026, 3, 13, 15, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 3, 13, 15, 0, 10, tzinfo=UTC),
            conversation=[
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
                {"type": "result", "result": "Done", "cost_usd": 0.01},
            ],
        )
        save_result(results_dir, "scan", result, backend="claude_cli", model=None)

        meta_files = list((results_dir / "scan").glob("*.meta.json"))
        ts = meta_files[0].name.replace(".meta.json", "")

        resp = client.get(f"/api/results/scan/{ts}")
        data = resp.json()
        assert data["has_conversation"] is True

        # Also test the conversation endpoint
        resp = client.get(f"/api/results/scan/{ts}/conversation")
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 2
        assert events[0]["type"] == "assistant"

    def test_conversation_not_found(self, tmp_path: Path):
        client, results_dir = _make_client(tmp_path)
        result = BackendResult(
            status="ok",
            output="Done",
            error=None,
            started_at=datetime(2026, 3, 13, 16, 0, 0, tzinfo=UTC),
            ended_at=datetime(2026, 3, 13, 16, 0, 5, tzinfo=UTC),
        )
        save_result(results_dir, "scan", result, backend="claude_cli", model=None)

        meta_files = list((results_dir / "scan").glob("*.meta.json"))
        ts = meta_files[0].name.replace(".meta.json", "")

        resp = client.get(f"/api/results/scan/{ts}/conversation")
        assert resp.status_code == 404
