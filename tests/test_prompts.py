from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from ai_automations.prompts import resolve_prompt


class TestResolvePrompt:
    def test_date_variable(self, tmp_path: Path):
        result = resolve_prompt("Today is {{date}}.", cwd=tmp_path, last_run=None)
        now = datetime.now(UTC)
        assert now.strftime("%Y-%m-%d") in result

    def test_datetime_variable(self, tmp_path: Path):
        result = resolve_prompt("Now: {{datetime}}", cwd=tmp_path, last_run=None)
        assert "T" in result  # ISO format
        assert "Now:" in result

    def test_last_run_never(self, tmp_path: Path):
        result = resolve_prompt("Last: {{last_run}}", cwd=tmp_path, last_run=None)
        assert "never" in result

    def test_last_run_with_value(self, tmp_path: Path):
        t = datetime(2026, 3, 10, 8, 0, 0, tzinfo=UTC)
        result = resolve_prompt("Last: {{last_run}}", cwd=tmp_path, last_run=t)
        assert "2026-03-10" in result

    def test_since_with_last_run(self, tmp_path: Path):
        t = datetime(2026, 3, 10, 8, 0, 0, tzinfo=UTC)
        result = resolve_prompt("Since {{since}}", cwd=tmp_path, last_run=t)
        assert "2026-03-10" in result

    def test_since_without_last_run_uses_24h_ago(self, tmp_path: Path):
        result = resolve_prompt("Since {{since}}", cwd=tmp_path, last_run=None)
        # Should contain a recent timestamp (within last 25h)
        assert "T" in result
        assert "Since" in result

    def test_git_log_variable(self, tmp_path: Path):
        with patch("ai_automations.prompts._git_log_since", return_value="abc123 fix bug"):
            result = resolve_prompt("Log: {{git_log}}", cwd=tmp_path, last_run=None)
        assert "abc123 fix bug" in result

    def test_git_log_no_repo(self, tmp_path: Path):
        # tmp_path is not a git repo, so git log should fail gracefully
        result = resolve_prompt("Log: {{git_log}}", cwd=tmp_path, last_run=None)
        assert "(no commits)" in result

    def test_unknown_variable_preserved(self, tmp_path: Path):
        result = resolve_prompt("{{unknown_var}}", cwd=tmp_path, last_run=None)
        assert "{{unknown_var}}" in result

    def test_whitespace_in_braces(self, tmp_path: Path):
        result = resolve_prompt("{{ date }}", cwd=tmp_path, last_run=None)
        now = datetime.now(UTC)
        assert now.strftime("%Y-%m-%d") in result

    def test_multiple_variables(self, tmp_path: Path):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        result = resolve_prompt(
            "Date={{date}} Last={{last_run}}",
            cwd=tmp_path,
            last_run=t,
        )
        assert "Date=" in result
        assert "Last=2026" in result

    def test_no_variables_unchanged(self, tmp_path: Path):
        result = resolve_prompt("plain prompt", cwd=tmp_path, last_run=None)
        assert result == "plain prompt"
