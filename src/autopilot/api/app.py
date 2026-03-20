from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from autopilot.api.routes_automations import router as automations_router
from autopilot.api.routes_health import router as health_router
from autopilot.api.routes_results import router as results_router
from autopilot.api.routes_webhooks import router as webhooks_router
from autopilot.config import parse_name_list
from autopilot.scheduler import Scheduler, daemon_loop


def create_app(scheduler: Scheduler | None = None) -> FastAPI:
    """Create the FastAPI application.

    If no scheduler is provided, one is built from environment variables:
      AUTOPILOT_DIR          — automations directory (default: ./automations)
      AUTOPILOT_BASE_DIR     — writable base dir (default: AUTOPILOT_DIR)
      AUTOPILOT_RESULTS_DIR  — results directory (default: ./results)
      AUTOPILOT_CONCURRENCY  — max parallel runs (default: 5)
      AUTOPILOT_POLL         — seconds between schedule checks (default: 60)
      AUTOPILOT_STATIC_DIR   — static files directory (default: /app/static)
    """
    owns_scheduler = scheduler is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal scheduler
        if scheduler is None:
            auto_dir = os.environ.get("AUTOPILOT_DIR", "./automations")
            include = parse_name_list(os.environ.get("AUTOPILOT_INCLUDE"))
            exclude = parse_name_list(os.environ.get("AUTOPILOT_EXCLUDE"))
            if include and exclude:
                raise ValueError("Cannot specify both AUTOPILOT_INCLUDE and AUTOPILOT_EXCLUDE")
            scheduler = Scheduler(
                automations_dir=Path(auto_dir),
                base_dir=Path(os.environ.get("AUTOPILOT_BASE_DIR", auto_dir)),
                results_dir=Path(os.environ.get("AUTOPILOT_RESULTS_DIR", "./results")),
                max_concurrency=int(os.environ.get("AUTOPILOT_CONCURRENCY", "5")),
                include=include,
                exclude=exclude,
            )
        app.state.scheduler = scheduler

        # Start the daemon loop as a background task when the app owns the scheduler
        daemon_task = None
        if owns_scheduler:
            poll = int(os.environ.get("AUTOPILOT_POLL", "60"))
            daemon_task = asyncio.create_task(
                daemon_loop(
                    scheduler.automations_dir,
                    base_dir=scheduler.base_dir,
                    results_dir=scheduler.results_dir,
                    poll_interval=poll,
                    max_concurrency=scheduler.max_concurrency,
                    scheduler=scheduler,
                    register_signals=False,
                )
            )

        yield

        if daemon_task is not None:
            scheduler.stop_event.set()
            for task in scheduler._tasks.values():
                task.cancel()
            await daemon_task

    app = FastAPI(title="Autopilot", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(automations_router)
    app.include_router(results_router)
    app.include_router(webhooks_router)

    # Static files for SPA (only if directory exists)
    # Check env var, then Docker path, then dev path (web/dist relative to repo root)
    static_dir = os.environ.get("AUTOPILOT_STATIC_DIR")
    if static_dir is None:
        pkg_root = Path(__file__).resolve().parent.parent.parent.parent
        for candidate in [Path("/app/static"), pkg_root / "web" / "dist"]:
            if candidate.is_dir():
                static_dir = str(candidate)
                break
    if static_dir and Path(static_dir).is_dir():
        static_path = Path(static_dir)
        app.mount("/assets", StaticFiles(directory=str(static_path / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(request: Request, full_path: str):
            # Serve actual files if they exist, otherwise fall back to index.html
            file_path = static_path / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_path / "index.html")

    return app
