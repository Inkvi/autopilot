from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _git_log_since(cwd: Path, since: datetime) -> str:
    """Get git log --oneline since a given datetime."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={since.isoformat()}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "(no commits)"


def resolve_prompt(
    template: str,
    *,
    cwd: Path | None,
    last_run: datetime | None,
) -> str:
    """Resolve template variables in a prompt string.

    Supported variables:
        {{date}}      — current date (YYYY-MM-DD)
        {{datetime}}  — current ISO datetime
        {{last_run}}  — last run ISO timestamp, or "never"
        {{since}}     — last run timestamp, or 24h ago (useful for --since flags)
        {{git_log}}   — git log --oneline since last run (or last 24h)
    """
    now = datetime.now(UTC)
    since = last_run or (now - timedelta(hours=24))

    replacements = {
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.isoformat(),
        "last_run": last_run.isoformat() if last_run else "never",
        "since": since.isoformat(),
        "git_log": _git_log_since(cwd, since) if cwd else "(no repo)",
    }

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()
        return replacements.get(key, match.group(0))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replace, template)
