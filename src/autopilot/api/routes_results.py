from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from autopilot.results import load_history

router = APIRouter(prefix="/api")


def _ts_from_started_at(started_at: str | None) -> str:
    """Derive the filename timestamp prefix from started_at ISO string."""
    if not started_at:
        return ""
    try:
        dt = datetime.fromisoformat(started_at)
        return dt.strftime("%Y-%m-%dT%H%M%SZ")
    except (ValueError, TypeError):
        return ""


@router.get("/results/{name}")
async def list_results(
    name: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    scheduler = request.app.state.scheduler
    history = load_history(scheduler.results_dir, name)
    result_dir = scheduler.results_dir / name
    runs = []
    for entry in history[:limit]:
        ts = _ts_from_started_at(entry.get("started_at"))
        # Read first 150 chars of output for preview
        output_preview = ""
        if ts:
            md_path = result_dir / f"{ts}.md"
            if md_path.exists():
                try:
                    raw = md_path.read_text(encoding="utf-8")[:200]
                    # Strip markdown headings and whitespace for a clean preview
                    output_preview = raw.strip().lstrip("#").strip()[:150]
                except OSError:
                    pass
        runs.append(
            {
                "timestamp": ts,
                "status": entry.get("status", "unknown"),
                "duration_s": entry.get("duration_s"),
                "cost_usd": entry.get("cost_usd"),
                "tokens_in": entry.get("tokens_in"),
                "tokens_out": entry.get("tokens_out"),
                "started_at": entry.get("started_at"),
                "ended_at": entry.get("ended_at"),
                "error": entry.get("error"),
                "backend": entry.get("backend"),
                "model": entry.get("model"),
                "output_preview": output_preview,
            }
        )
    return {"automation": name, "runs": runs}


@router.get("/results/{name}/live")
async def get_live_log(
    name: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Tail the log file of a currently running automation.

    Returns JSONL events starting from byte `offset`. The client should pass
    back `next_offset` on the next request to get only new data.
    """
    scheduler = request.app.state.scheduler
    if not scheduler.is_running(name):
        raise HTTPException(status_code=404, detail=f"'{name}' is not running")

    log_path = scheduler.get_log_path(name)
    if log_path is None or not log_path.exists():
        return {"events": [], "next_offset": offset, "running": True}

    try:
        raw = log_path.read_bytes()
    except OSError:
        return {"events": [], "next_offset": offset, "running": True}

    chunk = raw[offset:]
    next_offset = len(raw)

    events = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return {"events": events, "next_offset": next_offset, "running": True}


@router.get("/results/{name}/{ts}")
async def get_result(name: str, ts: str, request: Request) -> dict:
    scheduler = request.app.state.scheduler
    result_dir = scheduler.results_dir / name

    meta_path = result_dir / f"{ts}.meta.json"
    output_path = result_dir / f"{ts}.md"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"Result '{ts}' not found for '{name}'")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""

    conv_path = result_dir / f"{ts}.conversation.jsonl"

    return {
        "meta": {
            "timestamp": ts,
            "status": meta.get("status"),
            "duration_s": meta.get("duration_s"),
            "cost_usd": meta.get("cost_usd"),
            "tokens_in": meta.get("tokens_in"),
            "tokens_out": meta.get("tokens_out"),
            "started_at": meta.get("started_at"),
            "ended_at": meta.get("ended_at"),
            "error": meta.get("error"),
            "backend": meta.get("backend"),
            "model": meta.get("model"),
        },
        "output": output,
        "has_conversation": conv_path.exists(),
    }


@router.get("/results/{name}/{ts}/conversation")
async def get_conversation(name: str, ts: str, request: Request) -> dict:
    scheduler = request.app.state.scheduler
    result_dir = scheduler.results_dir / name
    conv_path = result_dir / f"{ts}.conversation.jsonl"

    if not conv_path.exists():
        raise HTTPException(status_code=404, detail="No conversation data available")

    events = []
    for line in conv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return {"events": events}
