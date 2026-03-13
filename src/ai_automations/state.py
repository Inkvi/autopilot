from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_STATE_PATH = Path(".state/scheduler-state.json")


def _state_path(base_dir: Path) -> Path:
    return base_dir / _DEFAULT_STATE_PATH


def load_state(base_dir: Path) -> dict[str, str]:
    """Load last-run state. Returns {automation_name: iso_timestamp}."""
    path = _state_path(base_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(base_dir: Path, state: dict[str, str]) -> None:
    """Persist state to disk."""
    path = _state_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def get_last_run(base_dir: Path, name: str) -> datetime | None:
    """Get last run timestamp for an automation, or None if never run."""
    state = load_state(base_dir)
    ts = state.get(name)
    if ts is None:
        return None
    return datetime.fromisoformat(ts)


def update_last_run(base_dir: Path, name: str, when: datetime | None = None) -> None:
    """Record that an automation was just run."""
    state = load_state(base_dir)
    state[name] = (when or datetime.now(UTC)).isoformat()
    save_state(base_dir, state)
