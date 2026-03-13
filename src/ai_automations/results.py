from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ai_automations.models import BackendResult


def _result_dir(results_dir: Path, name: str) -> Path:
    return results_dir / name


def _ts_prefix(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H%M%SZ")


def save_result(
    results_dir: Path,
    name: str,
    result: BackendResult,
    *,
    backend: str,
    model: str | None,
) -> Path:
    """Save a run result to disk. Returns the directory where files were written."""
    out_dir = _result_dir(results_dir, name)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = _ts_prefix(result.started_at)

    # Save AI output text
    output_path = out_dir / f"{prefix}.md"
    output_path.write_text(result.output or "", encoding="utf-8")

    # Save metadata
    duration = (result.ended_at - result.started_at).total_seconds()
    meta = {
        "status": result.status,
        "duration_s": round(duration, 2),
        "error": result.error,
        "backend": backend,
        "model": model,
        "started_at": result.started_at.isoformat(),
        "ended_at": result.ended_at.isoformat(),
    }
    meta_path = out_dir / f"{prefix}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return out_dir


def load_history(results_dir: Path, name: str) -> list[dict]:
    """Load all run metadata for an automation, sorted by time descending."""
    out_dir = _result_dir(results_dir, name)
    if not out_dir.is_dir():
        return []

    entries = []
    for meta_path in sorted(out_dir.glob("*.meta.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            entries.append(meta)
        except (json.JSONDecodeError, OSError):
            continue
    return entries
