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

`config.toml → AutomationConfig (pydantic) → clone_or_update_repos() → resolve_working_directory() → resolve_prompt() → check run_if condition → fetch remote skills → create worktree (or temp dir) → copy dotfiles → inject skills → Backend.run() (with retry) → BackendResult → save to results/ + notify channels → trigger on_success/on_error automations → worktree cleanup`

### Key abstractions

- **Backends** (`backends/base.py`): `Backend` protocol with a single `async run()` method. Five implementations (claude_cli, claude_sdk, codex_cli, openai_agents_sdk, gemini_cli) all shell out or use SDKs to execute prompts. Factory in `backends/__init__.py` via `get_backend()`. CLI backends share `shell.run_command_async()` for subprocess execution.

- **Channels** (`channels/base.py`): `Channel` protocol with `async notify()`. Three implementations: Slack webhooks, GitHub issues (via `gh` CLI), GitHub PRs (via `gh` CLI). Factory in `channels/__init__.py` via `get_channel()`. Configured per-automation as `[[channels]]` in TOML.

- **Prompt templates** (`prompts.py`): `resolve_prompt()` replaces `{{date}}`, `{{datetime}}`, `{{last_run}}`, `{{since}}`, `{{git_log}}` in prompt strings before sending to backends.

- **Repos** (`repos.py`): `clone_or_update_repos()` clones or fetches repos declared in `config.repos` to `<base_dir>/.repos/<name>/`. `resolve_working_directory()` maps a repo name to its cloned path, or passes through absolute paths. This enables containerized deployments where target repos aren't pre-existing.

- **Skills** (`skills.py`): `inject_skills()` symlinks individual skill folders from an automation's `skills/` directory into the worktree's `.agents/skills/`. Follows the [Agent Skills](https://agentskills.io) open standard. Existing skills in the target repo are preserved (not overwritten).

- **Worktree** (`worktree.py`): `create_worktree()` creates a fresh git worktree for each execution, copies dotfiles (`.env`, `.env.local`, `.envrc` by default, configurable via `copy_files`), injects skills. When `working_directory` is not set, execution runs in a temporary directory instead.

- **Scheduler** (`scheduler.py`): Two modes — `run_automation()` for single execution (used by `autopilot run` and system cron), and `daemon_loop()` for long-running process with parallel execution via `asyncio.Semaphore`. Includes retry logic with exponential backoff (`max_retries` config). Supports streaming output via `--stream` flag and log files. Chained automations via `on_success`/`on_error` trigger lists with cycle detection and depth limit (`MAX_CHAIN_DEPTH = 10`).

- **Conditions** (`conditions.py`): `check_condition()` evaluates `run_if` config. Three types: `git_changes` (commits since last run), `file_changes` (specific paths changed), `command` (shell command exit code).

- **API** (`api/`): FastAPI app with routes for automations (`GET /automations`, `POST /automations/{name}/run`, `POST /automations/{name}/stop`), results (`GET /results/{name}`, `GET /results/{name}/live`, `GET /results/{name}/{ts}`), and health (`GET /healthz`). Started via `autopilot daemon --health-port`.

- **Health endpoint** (`health.py`): Standalone HTTP server (legacy). The `api/` module supersedes this when using `--health-port`.

### State & persistence

- **State**: JSON file at `<base_dir>/.state/scheduler-state.json` tracking `{name: last_run_iso}`. Read/written via `state.py`.
- **Repos**: Cloned to `<base_dir>/.repos/<name>/` when `repos` is configured. Fetched and reset on each run.
- **Results**: Each run produces `results/<name>/<timestamp>.md` (output) + `<timestamp>.meta.json` (metadata) + `<timestamp>.log` (streaming log) + `<timestamp>.conversation.jsonl` (conversation events, if available). Read/written via `results.py`. Old results prunable via `autopilot prune`.
- **Skill repos**: Remote skills cloned to `<base_dir>/.skill-repos/<owner>/<repo>/<ref>/` via `repos.py:fetch_remote_skills()`.
- **Environment**: `.env` file loaded automatically via python-dotenv at CLI startup.

### Testing patterns

- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed.
- Backends are tested by mocking `run_command_async` (for CLI backends) or the SDK imports (for SDK backends).
- CLI commands are tested via `typer.testing.CliRunner`.
- Shared fixtures in `tests/conftest.py`: `tmp_dir`, `automations_dir`, `results_dir`, `sample_automation`, `ok_result`, `error_result`.
