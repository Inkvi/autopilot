from datetime import UTC, datetime

from ai_automations.models import BackendResult


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
    try:
        r.extra = "nope"  # type: ignore[attr-defined]
        assert False, "Should not be able to set arbitrary attributes"
    except AttributeError:
        pass
