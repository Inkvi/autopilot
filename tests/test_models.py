from datetime import UTC, datetime

import pytest

from autopilot.models import BackendResult


def test_backend_result_ok():
    t = datetime.now(UTC)
    r = BackendResult(status="ok", output="hello", error=None, started_at=t, ended_at=t)
    assert r.status == "ok"
    assert r.output == "hello"
    assert r.error is None


def test_backend_result_error():
    t = datetime.now(UTC)
    r = BackendResult(status="error", output="", error="boom", started_at=t, ended_at=t)
    assert r.status == "error"
    assert r.error == "boom"


def test_backend_result_slots():
    """BackendResult uses slots, so arbitrary attributes should fail."""
    t = datetime.now(UTC)
    r = BackendResult(status="ok", output="", error=None, started_at=t, ended_at=t)
    with pytest.raises(AttributeError):
        r.extra = "nope"  # type: ignore[attr-defined]
