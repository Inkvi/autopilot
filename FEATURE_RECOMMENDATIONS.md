# Autopilot Feature Recommendations

Analysis of existing capabilities and recommended new features for users automating their work.

## Existing Feature Summary

Autopilot is a model-agnostic CLI that runs AI automations on a schedule. Current capabilities:

### Execution
- **5 AI backends**: Claude CLI, Claude SDK, Codex CLI, OpenAI Agents SDK, Gemini CLI
- **Git worktree isolation**: Each run gets a clean worktree with dotfile copying
- **Retry with exponential backoff**: Configurable `max_retries`
- **Streaming output**: Real-time log tailing via `--stream` and API
- **Timeout enforcement** and **max turns control**
- **Conditional execution**: `run_if` supports git changes, file changes, custom commands

### Scheduling
- **Cron expressions** and **duration-based schedules** (e.g., `24h`, `30m`)
- **Daemon mode** with configurable concurrency (`asyncio.Semaphore`)
- **On-demand triggers** via API or CLI

### Observability
- **Token/cost tracking** with `autopilot costs`
- **Run history** with `autopilot history`
- **Conversation logging** (`.conversation.jsonl`)
- **Live log tailing** via web API
- **Web UI dashboard** with React frontend
- **Health endpoint** for monitoring

### Integration
- **Slack notifications** via webhooks
- **GitHub Issue creation** on completion
- **GitHub PR creation** with auto-commit and branch management
- **Remote Agent Skills** fetched from GitHub
- **Multi-repo cloning** with auto-update on each run
- **Dotfile copying** (`.env`, `.env.local`, `.envrc`, configurable)

### Configuration
- **Prompt templates**: `{{date}}`, `{{datetime}}`, `{{last_run}}`, `{{since}}`, `{{git_log}}`
- **Base config inheritance** via `base.toml`
- **Validation** via `autopilot validate`
- **Config-as-code**: Everything in `config.toml` per automation

### Deployment
- Local, system cron, Docker, Kubernetes (with PVC separation)

---

## Recommended New Features

### P0 — Critical gaps for real-world automation

#### 1. Chained Automations (Pipelines)

Allow automations to trigger other automations on completion. Today each automation is independent, but real workflows are sequential (e.g., "review code" → "if issues found, fix them" → "open PR").

```toml
[on_success]
trigger = ["create-pr"]

[on_error]
trigger = ["notify-oncall"]
```

**Impact**: High — this is the #1 gap. Users doing serious automation need multi-step workflows without external orchestration.

#### 2. Webhook Triggers

Add an HTTP endpoint that triggers automations on-demand from external events (GitHub webhooks, CI pipelines, Slack slash commands).

```
POST /api/automations/{name}/webhook
X-Webhook-Secret: <token>
Body: { "event": "push", "ref": "main", ... }
```

The webhook payload could be exposed as a `{{webhook_payload}}` template variable.

**Impact**: High — schedule-based polling is wasteful for event-driven work. Most automation platforms (Zapier, n8n) are event-first.

#### 3. Resource Budgets & Rate Limiting

Set per-automation or global spending limits to prevent runaway costs.

```toml
[budget]
max_cost_per_run = 0.50
max_cost_per_day = 10.00
max_tokens_per_day = 1000000
```

```bash
autopilot costs --budget   # show budget utilization
```

**Impact**: High — without guardrails, a misconfigured automation with a tight schedule can burn through API credits quickly. Essential for team/enterprise use.

---

### P1 — Developer experience improvements

#### 4. Generic Webhook Notification Channel

A channel type that POSTs JSON to any URL, letting users integrate with any service.

```toml
[[channels]]
type = "webhook"
url = "https://example.com/hook"
method = "POST"
headers = { "Authorization" = "Bearer {{env.TOKEN}}" }
```

**Impact**: High — unblocks dozens of integrations without building dedicated channel types for each service.

#### 5. Context Passing Between Runs

Allow an automation's output to feed into its next run as context, enabling iterative refinement.

```toml
[context]
include_last_output = true
max_context_runs = 3
```

New template variable: `{{last_output}}` containing the previous run's result.

**Impact**: Medium — many automation use cases are iterative (monitoring, tracking progress, refining code over multiple passes).

#### 6. Approval Gates

Pause an automation before execution or before notification/PR creation, requiring human approval via Slack reaction, web UI button, or API call.

```toml
[approval]
required = true
channel = "slack"
timeout = "1h"
```

**Impact**: High — full autonomy is risky for high-stakes automations. A human-in-the-loop option builds trust and enables use in regulated environments.

#### 7. Diff-Aware Prompt Templates

Automatically include git diffs and changed file lists in the prompt context.

```toml
[context]
include_diff = true          # {{git_diff}} variable
include_changed_files = true # {{changed_files}} variable
include_pr_body = true       # {{pr_body}} for PR-triggered runs
```

**Impact**: Medium — most code automation tasks need to understand *what changed*. Today users must manually craft git commands in prompts.

---

### P2 — Scale and ecosystem

#### 8. Automation Templates / Registry

A template library for common automation patterns.

```bash
autopilot template list
autopilot template install pr-reviewer
```

Example templates:
- Daily dependency update checker
- PR review bot
- Documentation staleness detector
- Security vulnerability scanner
- Test coverage reporter

**Impact**: High — lowers barrier to entry. Users shouldn't write prompts from scratch for common patterns.

#### 9. Parallel Steps Within an Automation

Allow a single automation to run multiple prompts in parallel and merge results.

```toml
[[steps]]
name = "review-frontend"
prompt = "Review the React components in src/components/"

[[steps]]
name = "review-backend"
prompt = "Review the API endpoints in src/api/"

[merge]
prompt = "Combine these reviews into a single report: {{step_outputs}}"
```

**Impact**: Medium — large codebases benefit from divide-and-conquer. Single monolithic prompts are slower and hit context limits.

#### 10. Result Aggregation & Reporting

Weekly/monthly digest reports aggregating automation outcomes.

```bash
autopilot report --since 7d --format markdown
autopilot report --since 30d --format html --email team@company.com
```

Metrics: success rates, costs, token usage trends, failure patterns.

**Impact**: Medium — ops teams need visibility into automation health over time.

#### 11. Secret Management

Support for external secret providers beyond `.env` files.

```toml
[secrets]
provider = "aws_secrets_manager"
prefix = "autopilot/"
```

Providers: AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault, or encrypted local store.

**Impact**: Medium — essential for enterprise environments with secret rotation requirements.

---

### P3 — Nice to have

#### 12. Enhanced Dry-Run / Simulation Mode

Extend `--dry-run` to simulate the full pipeline including condition checks, worktree creation, and channel notifications.

```bash
autopilot run my-auto --dry-run --simulate-channels --simulate-conditions
```

**Impact**: Low — saves time and money during automation development/debugging.

---

## Priority Matrix

| Priority | Feature | Impact | Effort |
|----------|---------|--------|--------|
| P0 | Chained Automations (Pipelines) | High | Medium |
| P0 | Webhook Triggers | High | Low |
| P0 | Resource Budgets & Rate Limiting | High | Low |
| P1 | Generic Webhook Channel | High | Low |
| P1 | Context Passing Between Runs | Medium | Low |
| P1 | Approval Gates | High | Medium |
| P1 | Diff-Aware Prompt Templates | Medium | Low |
| P2 | Automation Templates / Registry | High | High |
| P2 | Parallel Steps | Medium | High |
| P2 | Result Aggregation & Reporting | Medium | Medium |
| P2 | Secret Management | Medium | Medium |
| P3 | Enhanced Dry-Run Simulation | Low | Low |

## Quick Wins (Low effort, high value)

1. **Resource Budgets** — add `max_cost_per_run` field + check in scheduler
2. **Webhook Triggers** — one new API route + template variable
3. **Generic Webhook Channel** — one new channel implementation
4. **`{{last_output}}` template variable** — read last result file in `resolve_prompt()`
5. **`{{git_diff}}` template variable** — run `git diff` in `resolve_prompt()`
