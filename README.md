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
model = "claude-sonnet-4-5"
reasoning_effort = "medium"
timeout_seconds = 900
skip_permissions = true
max_turns = 10
max_retries = 2
copy_files = [".env", ".env.local", ".envrc"]

[[channels]]
type = "slack"
webhook_url_env = "SLACK_WEBHOOK_URL"
```

### Agent Skills

Place skill folders in `automations/<name>/skills/`. Each skill must follow the [Agent Skills](https://agentskills.io) format (a folder containing `SKILL.md`). Before execution, skills are symlinked into the worktree's `.agents/skills/` directory so the agent discovers them naturally. Existing skills in the target repo are preserved.

### Prompt template variables

| Variable | Value |
|---|---|
| `{{date}}` | Current date (`2026-03-12`) |
| `{{datetime}}` | Current ISO datetime |
| `{{last_run}}` | Last run timestamp, or `never` |
| `{{since}}` | Last run time, or 24h ago if never run |
| `{{git_log}}` | `git log --oneline` since last run |

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
autopilot list                    List all configured automations
autopilot daemon                  Start scheduler daemon
autopilot init <name>             Create template automation config
autopilot history <name>          Show run history
autopilot validate                Validate configs and check backend availability
autopilot prune <duration>        Remove old results (e.g. 30d, 720h)
```

### Daemon options

```
--poll-interval     Seconds between schedule checks (default: 60)
--max-concurrency   Max automations to run in parallel (default: 5)
--health-port       Port for HTTP health endpoint (disabled if unset)
```

## Scheduling

Two modes:

- **Daemon mode**: `autopilot daemon` — long-running process, handles all scheduling internally
- **System cron**: `crontab -e` with `autopilot run <name>` — each automation triggered by OS cron

## Environment

Create a `.env` file in the project root for secrets (loaded automatically):

```
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
```
