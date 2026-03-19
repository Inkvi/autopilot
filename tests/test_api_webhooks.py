from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
        config += f'schedule = "{auto.get("schedule", "24h")}"\n' if auto.get("schedule") else ""
        config += f'backend = "{auto.get("backend", "claude_cli")}"\n'
        if auto.get("webhook_secret"):
            config += f'webhook_secret = "{auto["webhook_secret"]}"\n'
        if auto.get("webhook_secret_env"):
            config += f'webhook_secret_env = "{auto["webhook_secret_env"]}"\n'
        (d / "config.toml").write_text(config, encoding="utf-8")

    scheduler = Scheduler(
        automations_dir=auto_dir,
        base_dir=tmp_path,
        results_dir=tmp_path / "results",
        max_concurrency=3,
    )
    app = create_app(scheduler)
    return TestClient(app).__enter__()


class TestWebhookTrigger:
    def test_not_found(self, tmp_path: Path):
        client = _make_client(tmp_path)
        resp = client.post(
            "/api/automations/nope/webhook",
            headers={"X-Webhook-Secret": "s"},
            json={},
        )
        assert resp.status_code == 404

    def test_no_secret_configured(self, tmp_path: Path):
        client = _make_client(tmp_path, [{"name": "scan", "schedule": "24h"}])
        resp = client.post(
            "/api/automations/scan/webhook",
            headers={"X-Webhook-Secret": "s"},
            json={},
        )
        assert resp.status_code == 400
        assert "not configured" in resp.json()["detail"]

    def test_missing_header(self, tmp_path: Path):
        client = _make_client(tmp_path, [{"name": "scan", "webhook_secret": "secret123"}])
        resp = client.post("/api/automations/scan/webhook", json={})
        assert resp.status_code == 401

    def test_wrong_secret(self, tmp_path: Path):
        client = _make_client(tmp_path, [{"name": "scan", "webhook_secret": "secret123"}])
        resp = client.post(
            "/api/automations/scan/webhook",
            headers={"X-Webhook-Secret": "wrong"},
            json={},
        )
        assert resp.status_code == 401

    def test_success(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "Do {{webhook_payload}}"\n'
            'schedule = "1h"\nbackend = "claude_cli"\n'
            'webhook_secret = "mysecret"\n',
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
            resp = client.post(
                "/api/automations/scan/webhook",
                headers={"X-Webhook-Secret": "mysecret"},
                json={"event": "push", "ref": "main"},
            )
            assert resp.status_code == 202
            assert resp.json()["status"] == "started"
            assert resp.json()["name"] == "scan"

    def test_conflict_if_running(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\n'
            'backend = "claude_cli"\nwebhook_secret = "s"\n',
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
            resp = client.post(
                "/api/automations/scan/webhook",
                headers={"X-Webhook-Secret": "s"},
                json={},
            )
            assert resp.status_code == 409

    def test_webhook_secret_env(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\n'
            'backend = "claude_cli"\nwebhook_secret_env = "MY_SECRET"\n',
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
            with patch.dict("os.environ", {"MY_SECRET": "envsecret"}):
                resp = client.post(
                    "/api/automations/scan/webhook",
                    headers={"X-Webhook-Secret": "envsecret"},
                    json={"test": True},
                )
            assert resp.status_code == 202

    def test_webhook_secret_env_not_set(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\n'
            'backend = "claude_cli"\nwebhook_secret_env = "MISSING_VAR"\n',
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
            with patch.dict("os.environ", {}, clear=False):
                # Ensure MISSING_VAR is not set
                import os

                os.environ.pop("MISSING_VAR", None)
                resp = client.post(
                    "/api/automations/scan/webhook",
                    headers={"X-Webhook-Secret": "anything"},
                    json={},
                )
            assert resp.status_code == 400
            assert "MISSING_VAR" in resp.json()["detail"]

    def test_non_json_body_uses_raw_text(self, tmp_path: Path):
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "scan"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "scan"\nprompt = "x"\nschedule = "1h"\n'
            'backend = "claude_cli"\nwebhook_secret = "s"\n',
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
            resp = client.post(
                "/api/automations/scan/webhook",
                headers={"X-Webhook-Secret": "s", "Content-Type": "text/plain"},
                content="token=abc&text=hello",
            )
            assert resp.status_code == 202

    def test_webhook_only_no_schedule(self, tmp_path: Path):
        """Automations with only webhook_secret and no schedule should work."""
        auto_dir = tmp_path / "automations"
        auto_dir.mkdir(exist_ok=True)
        d = auto_dir / "hook-only"
        d.mkdir()
        (d / "config.toml").write_text(
            'name = "hook-only"\nprompt = "x"\nbackend = "claude_cli"\nwebhook_secret = "s"\n',
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
            resp = client.post(
                "/api/automations/hook-only/webhook",
                headers={"X-Webhook-Secret": "s"},
                json={"event": "deploy"},
            )
            assert resp.status_code == 202
