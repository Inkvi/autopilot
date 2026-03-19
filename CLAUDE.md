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
autopilot run <name> --stream               # stream backend output in real-time
autopilot init <name>
autopilot history <name>
autopilot validate --dir ./automations
autopilot costs --since 7d
autopilot prune 30d --results-dir ./results
autopilot daemon --max-concurrency 5 --health-port 8080
autopilot daemon --dir /automations --base-dir /data --results-dir /data/results  # K8s mode
```

## Architecture

**Model-agnostic CLI** (`autopilot`) that runs AI automations on a schedule. Each automation is a folder containing `config.toml`, optional `skills/` directory (Agent Skills), and notification channel config.

### Data flow

`config.toml → AutomationConfig (pydantic) → clone_or_update_repos() → resolve_working_directory() → resolve_prompt(extra_vars) → check_condition(run_if) → fetch_remote_skills() → create worktree (or temp dir) → copy dotfiles → inject skills → Backend.run() (with retry) → BackendResult → save to results/ + notify channels → worktree cleanup`

### Key abstractions

- **Backends** (`backends/base.py`): `Backend` protocol with a single `async run()` method. Five implementations (claude_cli, claude_sdk, codex_cli, openai_agents_sdk, gemini_cli) all shell out or use SDKs to execute prompts. Factory in `backends/__init__.py` via `get_backend()`. CLI backends share `shell.run_command_async()` for subprocess execution.

- **Channels** (`channels/base.py`): `Channel` protocol with `async notify()`. Three implementations: Slack webhooks (`slack.py`), GitHub issues (`github_issue.py`), GitHub PRs (`github_pr.py`). Factory in `channels/__init__.py` via `get_channel()`. Configured per-automation as `[[channels]]` in TOML.

- **Prompt templates** (`prompts.py`): `resolve_prompt()` replaces `{{date}}`, `{{datetime}}`, `{{last_run}}`, `{{since}}`, `{{git_log}}`, and `{{webhook_payload}}` in prompt strings before sending to backends. Accepts `extra_vars` dict for additional template variables (used by webhook triggers).

- **Repos** (`repos.py`): `clone_or_update_repos()` clones or fetches repos declared in `config.repos` to `<base_dir>/.repos/<name>/`. `resolve_working_directory()` maps a repo name to its cloned path, or passes through absolute paths. This enables containerized deployments where target repos aren't pre-existing.

- **Skills** (`skills.py`): `inject_skills()` symlinks individual skill folders from an automation's `skills/` directory into the worktree's `.agents/skills/`. Follows the [Agent Skills](https://agentskills.io) open standard. Existing skills in the target repo are preserved (not overwritten).

- **Worktree** (`worktree.py`): `create_worktree()` creates a fresh git worktree for each execution, copies dotfiles (`.env`, `.env.local`, `.envrc` by default, configurable via `copy_files`), injects skills. When `working_directory` is not set, execution runs in a temporary directory instead.

- **Scheduler** (`scheduler.py`): Three trigger modes — scheduled (cron/interval via `daemon_loop()`), on-demand (via API `POST /api/automations/{name}/run`), and webhook-triggered (`POST /api/automations/{name}/webhook`). `run_automation()` handles single execution with retry logic (exponential backoff). `Scheduler` class manages concurrency via `asyncio.Semaphore`, running set tracking, and task cancellation.

- **API** (`api/`): FastAPI app in `app.py` with `create_app()` factory. Routes split across `routes_health.py` (healthz), `routes_automations.py` (list/detail/run/stop), `routes_results.py` (history/live/detail), and `routes_webhooks.py` (webhook triggers with HMAC auth). Started in daemon mode with `--health-port`.

### State & persistence

- **State**: JSON file at `<base_dir>/.state/scheduler-state.json` tracking `{name: last_run_iso}`. Read/written via `state.py`.
- **Repos**: Cloned to `<base_dir>/.repos/<name>/` when `repos` is configured. Fetched and reset on each run.
- **Results**: Each run produces `results/<name>/<timestamp>.md` (output) + `<timestamp>.meta.json` (metadata) + `<timestamp>.log` (streaming log) + optional `<timestamp>.conversation.jsonl` (conversation history). Read/written via `results.py`. Old results prunable via `autopilot prune`.
- **Environment**: `.env` file loaded automatically via python-dotenv at CLI startup.

### Testing patterns

- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Backends are tested by mocking `run_command_async` (for CLI backends) or the SDK imports (for SDK backends).
- CLI commands are tested via `typer.testing.CliRunner`.
- Shared fixtures in `tests/conftest.py`: `tmp_dir`, `automations_dir`, `results_dir`, `sample_automation`, `ok_result`, `error_result`.
