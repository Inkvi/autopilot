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
    runs = []
    for entry in history[:limit]:
        runs.append(
            {
                "timestamp": _ts_from_started_at(entry.get("started_at")),
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
            }
        )
    return {"automation": name, "runs": runs}


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
