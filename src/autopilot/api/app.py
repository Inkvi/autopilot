from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from autopilot.api.routes_automations import router as automations_router
from autopilot.api.routes_health import router as health_router
from autopilot.api.routes_results import router as results_router
from autopilot.scheduler import Scheduler


def create_app(scheduler: Scheduler) -> FastAPI:
    """Create the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.scheduler = scheduler
        yield

    app = FastAPI(title="Autopilot", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(automations_router)
    app.include_router(results_router)

    # Static files for SPA (only if directory exists)
    static_dir = os.environ.get("AUTOPILOT_STATIC_DIR", "/app/static")
    if Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
