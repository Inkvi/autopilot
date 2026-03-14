from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from autopilot.models import BackendResult, TokenUsage


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
    usage: TokenUsage | None = None,
) -> Path:
    """Save a run result to disk. Returns the directory where files were written."""
    out_dir = _result_dir(results_dir, name)
    out_dir.mkdir(parents=True, exist_ok=True)

    prefix = _ts_prefix(result.started_at)

    # Save AI output text
    output_path = out_dir / f"{prefix}.md"
    output_path.write_text(result.output or "", encoding="utf-8")

    # Save conversation events (if available)
    if result.conversation:
        conv_path = out_dir / f"{prefix}.conversation.jsonl"
        with open(conv_path, "w", encoding="utf-8") as f:
            for event in result.conversation:
                f.write(json.dumps(event) + "\n")

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
        "tokens_in": usage.tokens_in if usage else None,
        "tokens_out": usage.tokens_out if usage else None,
        "cost_usd": usage.cost_usd if usage else None,
    }
    meta_path = out_dir / f"{prefix}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return out_dir


def prune_results(results_dir: Path, older_than_seconds: float) -> int:
    """Delete result files older than the given age. Returns number of file pairs removed."""
    if not results_dir.is_dir():
        return 0

    from datetime import UTC, datetime

    cutoff = datetime.now(UTC) - __import__("datetime").timedelta(seconds=older_than_seconds)
    removed = 0

    for automation_dir in results_dir.iterdir():
        if not automation_dir.is_dir():
            continue
        for meta_path in list(automation_dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                started = datetime.fromisoformat(meta["started_at"])
                if started < cutoff:
                    meta_path.unlink()
                    # Remove matching .md and .log files
                    md_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".md"))
                    md_path.unlink(missing_ok=True)
                    log_path = meta_path.with_name(meta_path.name.replace(".meta.json", ".log"))
                    log_path.unlink(missing_ok=True)
                    conv_path = meta_path.with_name(
                        meta_path.name.replace(".meta.json", ".conversation.jsonl")
                    )
                    conv_path.unlink(missing_ok=True)
                    removed += 1
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    return removed


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
