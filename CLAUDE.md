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
autopilot run <name> --dry-run              # resolve prompt templates without executing
autopilot init <name>
autopilot history <name>
autopilot validate --dir ./automations
autopilot prune 30d --results-dir ./results
autopilot daemon --max-concurrency 5 --health-port 8080
```

## Architecture

**Model-agnostic CLI** (`autopilot`) that runs AI automations on a schedule. Each automation is a folder containing `config.toml`, optional `skills/` directory (Agent Skills), and notification channel config.

### Data flow

`config.toml → AutomationConfig (pydantic) → resolve_prompt() → create worktree → copy dotfiles → inject skills → Backend.run() (with retry) → BackendResult → save to results/ + notify channels → worktree cleanup`

### Key abstractions

- **Backends** (`backends/base.py`): `Backend` protocol with a single `async run()` method. Five implementations (claude_cli, claude_sdk, codex_cli, openai_agents_sdk, gemini_cli) all shell out or use SDKs to execute prompts. Factory in `backends/__init__.py` via `get_backend()`. CLI backends share `shell.run_command_async()` for subprocess execution.

- **Channels** (`channels/base.py`): `Channel` protocol with `async notify()`. Currently only Slack webhooks. Factory in `channels/__init__.py` via `get_channel()`. Configured per-automation as `[[channels]]` in TOML.

- **Prompt templates** (`prompts.py`): `resolve_prompt()` replaces `{{date}}`, `{{datetime}}`, `{{last_run}}`, `{{since}}`, `{{git_log}}` in prompt strings before sending to backends.

- **Skills** (`skills.py`): `inject_skills()` symlinks individual skill folders from an automation's `skills/` directory into the worktree's `.agents/skills/`. Follows the [Agent Skills](https://agentskills.io) open standard. Existing skills in the target repo are preserved (not overwritten).

- **Worktree** (`worktree.py`): `run_with_worktree()` creates a fresh git worktree for each execution, copies dotfiles (`.env`, `.env.local`, `.envrc` by default, configurable via `copy_files`), injects skills, runs the backend, then cleans up.

- **Scheduler** (`scheduler.py`): Two modes — `run_automation()` for single execution (used by `autopilot run` and system cron), and `daemon_loop()` for long-running process with parallel execution via `asyncio.Semaphore`. All executions run in git worktrees. Includes retry logic with exponential backoff (`max_retries` config).

- **Health endpoint** (`health.py`): Optional HTTP server started in daemon mode (`--health-port`). Returns JSON with uptime and automation count.

### State & persistence

- **State**: JSON file at `.state/scheduler-state.json` tracking `{name: last_run_iso}`. Read/written via `state.py`.
- **Results**: Each run produces `results/<name>/<timestamp>.md` (output) + `<timestamp>.meta.json` (metadata). Read/written via `results.py`. Old results prunable via `autopilot prune`.
- **Environment**: `.env` file loaded automatically via python-dotenv at CLI startup.

### Testing patterns

- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Backends are tested by mocking `run_command_async` (for CLI backends) or the SDK imports (for SDK backends).
- CLI commands are tested via `typer.testing.CliRunner`.
- Shared fixtures in `tests/conftest.py`: `tmp_dir`, `automations_dir`, `results_dir`, `sample_automation`, `ok_result`, `error_result`.
