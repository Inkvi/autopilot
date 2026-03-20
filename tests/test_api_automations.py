from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from autopilot.api.app import create_app
from autopilot.scheduler import Scheduler


def _make_client(tmp_path: Path, automations: list[dict] | None = None) -> TestClient:
    auto_dir = tmp_path / "automations"
    auto_dir.mkdir(exist_ok=True)

    for auto in automations or []:
        d = auto_dir / auto["name"]
        d.mkdir()
        config = f'name = "{auto["name"]}"\n'
        config += 'prompt = "Do stuff."\n'
        config += f'schedule = "{auto.get("schedule", "24h")}"\n'
        config += f'backend = "{auto.get("backend", "claude_cli")}"\n'
        if auto.get("model"):
            config += f'model = "{auto["model"]}"\n'
        (d / "config.toml").write_text(config, encoding="utf-8")

    scheduler = Scheduler(
        automations_dir=auto_dir,
        base_dir=tmp_path,
        results_dir=tmp_path / "results",
        max_concurrency=3,
    )
    app = create_app(scheduler)
    # Use context manager to trigger lifespan
    return TestClient(app).__enter__()


class TestListAutomations:
    def test_empty(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.get("/api/automations")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_automations(self, tmp_path: Path):
        client = _make_client(tmp_path, [{"name": "scan", "model": "claude-sonnet-4-6"}])
        resp = client.get("/api/automations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "scan"
        assert data[0]["backend"] == "claude_cli"
        assert data[0]["model"] == "claude-sonnet-4-6"
        assert data[0]["is_running"] is False

    def test_preserves_multi_backend_shape(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\n'
            'prompt = "x"\n'
            'schedule = "1h"\n'
            'backend = ["claude_cli", "gemini_cli"]\n'
            'model = { claude_cli = "claude-sonnet-4-5", gemini_cli = "gemini-2.5-pro" }\n',
            encoding="utf-8",
        )
        scheduler = Scheduler(
            automations_dir=auto_dir,
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        app = create_app(scheduler)
        with TestClient(app) as client:
            data = client.get("/api/automations").json()
            assert data[0]["backend"] == ["claude_cli", "gemini_cli"]
            assert data[0]["model"] == {
                "claude_cli": "claude-sonnet-4-5",
                "gemini_cli": "gemini-2.5-pro",
            }

    def test_shows_running_status(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\nbackend = "claude_cli"\n',
            encoding="utf-8",
        )
        scheduler = Scheduler(
            automations_dir=auto_dir,
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        scheduler.running["scan"] = None
        app = create_app(scheduler)
        with TestClient(app) as client:
            data = client.get("/api/automations").json()
            assert data[0]["is_running"] is True


class TestGetAutomation:
    def test_not_found(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.get("/api/automations/nope")
        assert resp.status_code == 404

    def test_returns_detail(self, tmp_path: Path):
        client = _make_client(tmp_path, [{"name": "scan"}])
        resp = client.get("/api/automations/scan")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "scan"
        assert "timeout_seconds" in data
        assert "max_retries" in data


class TestTriggerRun:
    def test_not_found(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.post("/api/automations/nope/run")
        assert resp.status_code == 404

    def test_starts_run(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\nbackend = "claude_cli"\n',
            encoding="utf-8",
        )
        scheduler = Scheduler(
            automations_dir=auto_dir,
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        app = create_app(scheduler)
        with TestClient(app) as client:
            resp = client.post("/api/automations/scan/run")
            assert resp.status_code == 202
            assert resp.json()["status"] == "started"

    def test_conflict_if_running(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\nbackend = "claude_cli"\n',
            encoding="utf-8",
        )
        scheduler = Scheduler(
            automations_dir=auto_dir,
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        scheduler.running["scan"] = None
        app = create_app(scheduler)
        with TestClient(app) as client:
            resp = client.post("/api/automations/scan/run")
            assert resp.status_code == 409
