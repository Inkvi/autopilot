from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from autopilot.api.routes_automations import router as automations_router
from autopilot.api.routes_health import router as health_router
from autopilot.api.routes_results import router as results_router
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
            scheduler = Scheduler(
                automations_dir=Path(auto_dir),
                base_dir=Path(os.environ.get("AUTOPILOT_BASE_DIR", auto_dir)),
                results_dir=Path(os.environ.get("AUTOPILOT_RESULTS_DIR", "./results")),
                max_concurrency=int(os.environ.get("AUTOPILOT_CONCURRENCY", "5")),
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
                )
            )

        yield

        if daemon_task is not None:
            scheduler.stop_event.set()
            await daemon_task

    app = FastAPI(title="Autopilot", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(automations_router)
    app.include_router(results_router)

    # Static files for SPA (only if directory exists)
    _pkg_static = Path(__file__).resolve().parent.parent.parent.parent / "web" / "dist"
    _default_static = str(_pkg_static) if _pkg_static.is_dir() else "/app/static"
    static_dir = os.environ.get("AUTOPILOT_STATIC_DIR", _default_static)
    if Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
