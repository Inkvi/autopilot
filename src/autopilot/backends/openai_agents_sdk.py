from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autopilot.models import BackendResult


def _load_agents_sdk() -> Any:
    try:
        import agents as openai_agents  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        try:
            import openai_agents  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "openai_agents_sdk backend requires the OpenAI Agents SDK. "
                "Install it and configure OPENAI_API_KEY."
            ) from exc
    return openai_agents


def _invoke_runner_sync(runner: Any, agent: Any, prompt: str) -> Any:
    if hasattr(runner, "run_sync"):
        try:
            return runner.run_sync(agent, input=prompt)
        except TypeError:
            return runner.run_sync(agent, prompt)
    if hasattr(runner, "run"):
        try:
            result = runner.run(agent, input=prompt)
        except TypeError:
            result = runner.run(agent, prompt)
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result
    raise RuntimeError("OpenAI Agents SDK Runner does not expose run/run_sync")


def _extract_result_text(result: Any) -> str:
    for attr in ("final_output", "output", "result"):
        if hasattr(result, attr):
            value = getattr(result, attr)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        for key in ("final_output", "output", "result"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _build_model_settings(openai_agents: Any, reasoning_effort: str | None) -> Any:
    if reasoning_effort is None or not hasattr(openai_agents, "ModelSettings"):
        return None
    model_settings_cls = openai_agents.ModelSettings
    try:
        parameters = inspect.signature(model_settings_cls).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "reasoning" in parameters:
        return model_settings_cls(reasoning={"effort": reasoning_effort})
    if "reasoning_effort" in parameters:
        return model_settings_cls(reasoning_effort=reasoning_effort)
    try:
        return model_settings_cls(reasoning={"effort": reasoning_effort})
    except Exception:
        return model_settings_cls(reasoning_effort=reasoning_effort)


def _run_sync(
    prompt: str,
    model: str | None,
    reasoning_effort: str | None,
) -> str:
    openai_agents = _load_agents_sdk()
    if not hasattr(openai_agents, "Agent") or not hasattr(openai_agents, "Runner"):
        raise RuntimeError("OpenAI Agents SDK does not provide Agent/Runner")

    agent_kwargs: dict[str, Any] = {"name": "Autopilot Automation"}
    if model:
        agent_kwargs["model"] = model
    model_settings = _build_model_settings(openai_agents, reasoning_effort)
    if model_settings is not None:
        agent_kwargs["model_settings"] = model_settings

    agent = openai_agents.Agent(**agent_kwargs)
    result = _invoke_runner_sync(openai_agents.Runner, agent, prompt)
    text = _extract_result_text(result)
    if not text:
        raise RuntimeError("OpenAI Agents SDK returned an empty response")
    return text


class OpenAIAgentsSDKBackend:
    async def run(
        self,
        prompt: str,
        *,
        cwd: Path,
        timeout_seconds: int,
        model: str | None,
        reasoning_effort: str | None,
        skip_permissions: bool,
        max_turns: int,
    ) -> BackendResult:
        started = datetime.now(UTC)
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(_run_sync, prompt, model, reasoning_effort),
                timeout=timeout_seconds,
            )
            return BackendResult(
                status="ok",
                output=text,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except TimeoutError:
            return BackendResult(
                status="error",
                output="",
                error=f"OpenAI Agents SDK timed out after {timeout_seconds}s",
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except Exception as exc:
            return BackendResult(
                status="error",
                output="",
                error=str(exc),
                started_at=started,
                ended_at=datetime.now(UTC),
            )
