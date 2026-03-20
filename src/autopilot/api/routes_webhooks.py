from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from autopilot.config import discover_automations

router = APIRouter(prefix="/api")


@router.post("/automations/{name}/webhook")
async def webhook_trigger(name: str, request: Request):
    scheduler = request.app.state.scheduler

    configs = discover_automations(
        scheduler.automations_dir, include=scheduler.include, exclude=scheduler.exclude
    )
    config = next((c for c in configs if c.name == name), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Automation '{name}' not found")

    if config.webhook_secret is None and config.webhook_secret_env is None:
        raise HTTPException(status_code=400, detail="Webhook not configured for this automation")

    try:
        expected = config.resolve_webhook_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provided = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Read request body — try JSON first, fall back to raw text
    try:
        body = await request.json()
        payload_str = json.dumps(body)
    except Exception:
        raw = await request.body()
        payload_str = raw.decode("utf-8", errors="replace")

    try:
        await scheduler.trigger_run(name, extra_vars={"webhook_payload": payload_str})
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "already running" in detail else 404
        raise HTTPException(status_code=status, detail=detail) from exc

    return JSONResponse(
        status_code=202,
        content={"status": "started", "name": name},
    )
