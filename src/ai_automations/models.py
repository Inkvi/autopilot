from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class BackendResult:
    status: str  # "ok" | "error"
    output: str  # AI text output
    error: str | None
    started_at: datetime
    ended_at: datetime
