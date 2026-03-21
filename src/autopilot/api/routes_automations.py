from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from autopilot.config import discover_automations, is_cron_schedule
from autopilot.results import load_history
from autopilot.state import get_last_run

router = APIRouter(prefix="/api")


def _automation_summary(config, scheduler) -> dict:
    last_run = get_last_run(scheduler.base_dir, config.name)
    last_status = None
    if last_run is not None:
        history = load_history(scheduler.results_dir, config.name)
        if history:
            last_status = history[0].get("status")

    next_run = None
    if config.schedule is not None and is_cron_schedule(config.schedule):
        from datetime import UTC, datetime

        from croniter import croniter

        base = last_run if last_run is not None else datetime.now(UTC)
        cron = croniter(config.schedule, base)
        next_run = cron.get_next(datetime).isoformat()
    elif config.schedule is not None and last_run is not None:
        next_run = (last_run + timedelta(seconds=config.schedule_seconds)).isoformat()

    return {
        "name": config.name,
        "backend": config.backend,
        "model": config.model_display,
        "schedule": config.schedule,
        "working_directory": config.working_directory,
        "last_run": last_run.isoformat() if last_run else None,
        "last_status": last_status,
        "next_run": next_run,
        "is_running": scheduler.is_running(config.name),
    }


@router.get("/automations")
async def list_automations(request: Request) -> list[dict]:
    scheduler = request.app.state.scheduler
    configs = discover_automations(
        scheduler.automations_dir, include=scheduler.include, exclude=scheduler.exclude
    )
    return [_automation_summary(c, scheduler) for c in configs]


@router.get("/automations/{name}")
async def get_automation(name: str, request: Request) -> dict:
    scheduler = request.app.state.scheduler
    configs = discover_automations(
        scheduler.automations_dir, include=scheduler.include, exclude=scheduler.exclude
    )
    config = next((c for c in configs if c.name == name), None)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Automation '{name}' not found")

    summary = _automation_summary(config, scheduler)
    summary["repos"] = config.repos
    summary["timeout_seconds"] = config.timeout_seconds
    summary["max_retries"] = config.max_retries
    summary["prompt"] = config.prompt
    summary["reasoning_effort"] = config.reasoning_effort
    summary["skip_permissions"] = config.skip_permissions
    summary["max_turns"] = config.max_turns
    summary["copy_files"] = config.copy_files
    summary["run_if"] = config.run_if.model_dump() if config.run_if else None
    return summary


@router.post("/automations/{name}/run")
async def trigger_run(name: str, request: Request):
    scheduler = request.app.state.scheduler

    try:
        await scheduler.trigger_run(name)
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "already running" in detail else 404
        raise HTTPException(status_code=status, detail=detail) from exc

    return JSONResponse(
        status_code=202,
        content={"status": "started", "name": name},
    )


@router.post("/automations/{name}/stop")
async def stop_run(name: str, request: Request):
    scheduler = request.app.state.scheduler

    try:
        await scheduler.stop_run(name)
    except ValueError as exc:
        detail = str(exc)
        status = 409 if "not running" in detail else 404
        raise HTTPException(status_code=status, detail=detail) from exc

    return JSONResponse(
        status_code=200,
        content={"status": "stopped", "name": name},
    )
