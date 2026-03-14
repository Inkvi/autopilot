from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from autopilot.api.app import create_app
from autopilot.scheduler import Scheduler


class TestHealthEndpoint:
    def test_healthz_returns_json(self, tmp_path: Path):
        scheduler = Scheduler(
            automations_dir=tmp_path / "automations",
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        scheduler.automations_count = 5
        app = create_app(scheduler)
        with TestClient(app) as client:
            response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["automations_loaded"] == 5
        assert isinstance(body["uptime_s"], float)

    def test_healthz_uptime_increases(self, tmp_path: Path):
        scheduler = Scheduler(
            automations_dir=tmp_path / "automations",
            base_dir=tmp_path,
            results_dir=tmp_path / "results",
            max_concurrency=3,
        )
        scheduler.started_at = time.monotonic() - 100
        app = create_app(scheduler)
        with TestClient(app) as client:
            body = client.get("/healthz").json()
        assert body["uptime_s"] >= 100
