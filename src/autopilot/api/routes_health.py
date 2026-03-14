from __future__ import annotations

import time

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    scheduler = request.app.state.scheduler
    return {
        "status": "ok",
        "uptime_s": round(time.monotonic() - scheduler.started_at, 1),
        "automations_loaded": scheduler.automations_count,
    }
