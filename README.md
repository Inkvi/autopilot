# Autopilot — AI Automations CLI

Model-agnostic CLI tool that runs AI automations on a schedule. File-system configured, runnable locally or headlessly on VPS/K8s.

## Install

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
```

## Quick start

```bash
# Create your first automation
autopilot init daily-scan

# Edit the generated config
$EDITOR automations/daily-scan/config.toml

# Test it (show resolved prompt without running)
autopilot run daily-scan --dry-run

# Run it once
autopilot run daily-scan

# Run with streaming output
autopilot run daily-scan --stream

# Check results
autopilot history daily-scan
```

## Automation config

Each automation is a folder in the `automations/` directory:

```
automations/
  daily-bug-scan/
    config.toml          # Required: automation configuration
    skills/              # Optional: Agent Skills (agentskills.io)
      code-review/
        SKILL.md
      custom-lint/
        SKILL.md
        scripts/run.sh
```

### config.toml

```toml
name = "daily-bug-scan"
prompt = """
Scan commits since {{since}} for likely bugs and propose minimal fixes.
Recent git log:
{{git_log}}
"""
working_directory = "/path/to/project"
schedule = "24h"
backend = "claude_cli"
model = "claude-sonnet-4-6"
reasoning_effort = "medium"
timeout_seconds = 900
skip_permissions = true
max_turns = 10
max_retries = 2
copy_files = [".env", ".env.local", ".envrc"]

# Webhook trigger (optional — enables event-driven execution)
webhook_secret_env = "MY_WEBHOOK_SECRET"

# Conditional execution (optional)
[run_if]
type = "git_changes"    # only run if new commits since last run
# type = "file_changes"  # only run if specific paths changed
# paths = ["src/", "config/"]
# type = "command"       # only run if shell command exits 0
# cmd = "test -f /tmp/flag"

[[channels]]
type = "slack"
webhook_url_env = "SLACK_WEBHOOK_URL"

[[channels]]
type = "github_issue"
repo = "org/repo"
labels = ["autopilot"]

[[channels]]
type = "github_pr"
repo = "org/repo"
draft = true
```

Automations must have at least one trigger: `schedule` or `webhook_secret`/`webhook_secret_env`. Both can be set together.

### Repos

Automations can declare git repositories to clone before execution. This is useful in containerized environments where the target repos aren't pre-existing on disk.

```toml
name = "cross-repo-audit"
prompt = "Audit these services for security issues."
repos = [
  "https://github.com/org/proof-api",
  "https://github.com/org/relayer",
  "https://github.com/org/accounts-api",
]
working_directory = "proof-api"  # matches repo name
schedule = "7d"
backend = "claude_cli"
```

Repos are cloned to `<base-dir>/.repos/<name>/` and updated (fetch + reset) on each run. The `working_directory` can reference a repo by name — autopilot resolves it to the cloned path automatically.

If no `working_directory` is set, the automation runs in a temporary directory (useful for tasks that don't operate on a repo).

### Agent Skills

Place skill folders in `automations/<name>/skills/`. Each skill must follow the [Agent Skills](https://agentskills.io) format (a folder containing `SKILL.md`). Before execution, skills are symlinked into the worktree's `.agents/skills/` directory so the agent discovers them naturally. Existing skills in the target repo are preserved.

Remote skills can also be fetched from GitHub repos:

```toml
skills = [
  "https://github.com/org/repo/tree/main/skills/code-review",
  "https://github.com/org/repo/tree/main/skills/custom-lint",
]
```

### Shared base config

Create `automations/base.toml` to share settings across all automations:

```toml
backend = "claude_cli"
schedule = "24h"
timeout_seconds = 600
```

Individual automation configs override base settings. `name` and `prompt` cannot appear in `base.toml`.

### Prompt template variables

| Variable | Value |
|---|---|
| `{{date}}` | Current date (e.g. `2026-03-19`) |
| `{{datetime}}` | Current ISO datetime |
| `{{last_run}}` | Last run timestamp, or `never` |
| `{{since}}` | Last run time, or 24h ago if never run |
| `{{git_log}}` | `git log --oneline` since last run |
| `{{webhook_payload}}` | JSON body (or raw text) from webhook trigger |

### Backends

| Backend | Tool |
|---|---|
| `claude_cli` | Claude Code CLI |
| `claude_sdk` | Claude Agent SDK (Python) |
| `codex_cli` | Codex CLI |
| `openai_agents_sdk` | OpenAI Agents SDK (Python) |
| `gemini_cli` | Gemini CLI |

## CLI commands

```
autopilot run <name>              Run a specific automation once
autopilot run <name> --dry-run    Show resolved prompt without executing
autopilot run <name> --stream     Stream backend output in real-time
autopilot list                    List all configured automations
autopilot daemon                  Start scheduler daemon
autopilot init <name>             Create template automation config
autopilot history <name>          Show run history
autopilot validate                Validate configs and check backend availability
autopilot costs                   Show token usage and costs
autopilot prune <duration>        Remove old results (e.g. 30d, 720h)
```

### Daemon options

```
--base-dir          Writable dir for state, repos, etc. (defaults to --dir)
--poll-interval     Seconds between schedule checks (default: 60)
--max-concurrency   Max automations to run in parallel (default: 5)
--health-port       Port for HTTP health endpoint (disabled if unset)
```

## Scheduling

Three trigger modes:

- **Daemon mode**: `autopilot daemon` — long-running process, handles all scheduling internally
- **System cron**: `crontab -e` with `autopilot run <name>` — each automation triggered by OS cron
- **Webhook**: `POST /api/automations/{name}/webhook` — event-driven, triggered by external systems

## Webhook triggers

Trigger automations from external events (GitHub webhooks, CI pipelines, Slack slash commands):

```toml
name = "deploy-review"
prompt = "Review deployment: {{webhook_payload}}"
backend = "claude_cli"
webhook_secret_env = "DEPLOY_WEBHOOK_SECRET"
```

```bash
curl -X POST http://localhost:8080/api/automations/deploy-review/webhook \
  -H "X-Webhook-Secret: $DEPLOY_WEBHOOK_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"event": "push", "ref": "main"}'
```

The webhook payload (JSON or raw text) is available as `{{webhook_payload}}` in the prompt. Authentication uses timing-safe comparison of the `X-Webhook-Secret` header.

## API

When running with `--health-port`, a REST API is available:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/healthz` | Health check (status, uptime, automation count) |
| `GET` | `/api/automations` | List all automations with status |
| `GET` | `/api/automations/{name}` | Get automation details |
| `POST` | `/api/automations/{name}/run` | Trigger on-demand run |
| `POST` | `/api/automations/{name}/stop` | Stop running automation |
| `POST` | `/api/automations/{name}/webhook` | Webhook trigger (requires `X-Webhook-Secret`) |
| `GET` | `/api/results/{name}` | Run history |
| `GET` | `/api/results/{name}/live` | Live tail of running automation |
| `GET` | `/api/results/{name}/{ts}` | Full result details |
| `GET` | `/api/results/{name}/{ts}/conversation` | Conversation steps (JSONL) |

## Web dashboard

A React-based web dashboard is available when running in daemon mode with `--health-port`. It provides a UI for viewing automations, run history, live streaming logs, and conversation steps.

In production (Docker), the frontend is built and served as static files by FastAPI. For local development:

```bash
# Terminal 1: API server
AUTOPILOT_DIR=./automations AUTOPILOT_RESULTS_DIR=./results \
  uv run uvicorn autopilot.api.app:create_app --factory --host 0.0.0.0 --port 8080 --reload --reload-dir src

# Terminal 2: Vite dev server
cd web && npm run dev
```

Or use the `Procfile.dev` with a process manager like `foreman` or `overmind`.

## Notification channels

| Channel | Description | Required config |
|---|---|---|
| `slack` | Post results to Slack webhook | `webhook_url` or `webhook_url_env` |
| `github_issue` | Create GitHub issue with results | `repo` (e.g. `org/repo`), optional `labels` |
| `github_pr` | Create/update PR with changes | `repo`, optional `draft` |

GitHub channels require the `gh` CLI to be authenticated.

## Kubernetes

For K8s deployments, use `--base-dir` to separate writable state from read-only config:

```bash
autopilot daemon \
  --dir /automations \        # baked into Docker image (read-only)
  --base-dir /data \           # PVC — repos, state, etc.
  --results-dir /data/results \
  --max-concurrency 3 \
  --health-port 8080
```

Repos declared in automation configs are cloned to `/data/.repos/` automatically. No init containers needed for repo setup.

## Environment

Create a `.env` file in the project root for secrets (loaded automatically):

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```
