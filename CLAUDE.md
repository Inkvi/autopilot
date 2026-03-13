# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable)
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# Run tests
python -m pytest tests/
python -m pytest tests/test_config.py               # single file
python -m pytest tests/test_config.py::TestParseSchedule::test_hours  # single test

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# CLI
autopilot list --dir ./automations
autopilot run <name> --dir ./automations --results-dir ./results
autopilot init <name>
autopilot history <name>
autopilot daemon
```

## Architecture

**Model-agnostic CLI** (`autopilot`) that runs AI automations on a schedule. Each automation is a TOML file defining a prompt, backend, schedule, and optional notification channels.

### Data flow

`TOML config → AutomationConfig (pydantic) → Backend.run() → BackendResult → save to results/ + notify channels`

### Key abstractions

- **Backends** (`backends/base.py`): `Backend` protocol with a single `async run()` method. Five implementations (claude_cli, claude_sdk, codex_cli, openai_agents_sdk, gemini_cli) all shell out or use SDKs to execute prompts. Factory in `backends/__init__.py` via `get_backend()`. CLI backends share `shell.run_command_async()` for subprocess execution.

- **Channels** (`channels/base.py`): `Channel` protocol with `async notify()`. Currently only Slack webhooks. Factory in `channels/__init__.py` via `get_channel()`. Configured per-automation as `[[channels]]` in TOML.

- **Scheduler** (`scheduler.py`): Two modes — `run_automation()` for single execution (used by `autopilot run` and system cron), and `daemon_loop()` for long-running process. Scheduling is poll-based: compare `now - last_run` against config interval.

### State & persistence

- **State**: JSON file at `.state/scheduler-state.json` tracking `{name: last_run_iso}`. Read/written via `state.py`.
- **Results**: Each run produces `results/<name>/<timestamp>.md` (output) + `<timestamp>.meta.json` (metadata). Read/written via `results.py`.

### Testing patterns

- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Backends are tested by mocking `run_command_async` (for CLI backends) or the SDK imports (for SDK backends).
- CLI commands are tested via `typer.testing.CliRunner`.
- Shared fixtures in `tests/conftest.py`: `tmp_dir`, `automations_dir`, `results_dir`, `sample_toml`, `ok_result`, `error_result`.
