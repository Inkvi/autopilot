from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from autopilot.backends import get_backend
from autopilot.backends.claude_cli import ClaudeCLIBackend, _build_command
from autopilot.backends.codex_cli import (
    CodexCLIBackend,
    _extract_fallback_text,
    _sanitize_output,
)
from autopilot.backends.gemini_cli import (
    GeminiCLIBackend,
    _extract_markdown_from_payload,
    _extract_text,
    _iter_json_payloads,
    _summarize_error,
)
from autopilot.backends.openai_agents_sdk import _extract_result_text

_CLAUDE_RUN = "autopilot.backends.claude_cli.run_command_async"
_CODEX_RUN = "autopilot.backends.codex_cli.run_command_async"
_GEMINI_RUN = "autopilot.backends.gemini_cli.run_command_async"

# --- get_backend factory ---


class TestGetBackend:
    def test_claude_cli(self):
        b = get_backend("claude_cli")
        assert isinstance(b, ClaudeCLIBackend)

    def test_codex_cli(self):
        b = get_backend("codex_cli")
        assert isinstance(b, CodexCLIBackend)

    def test_gemini_cli(self):
        b = get_backend("gemini_cli")
        assert isinstance(b, GeminiCLIBackend)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend("gpt4_cli")


# --- claude_cli ---


class TestClaudeCLIBuildCommand:
    def test_minimal(self):
        args = _build_command("hello")
        assert args == ["claude", "-p", "hello", "--output-format", "text",
                         "--dangerously-skip-permissions"]

    def test_no_skip_permissions(self):
        args = _build_command("hello", skip_permissions=False)
        assert "--dangerously-skip-permissions" not in args

    def test_with_model(self):
        args = _build_command("hello", model="sonnet")
        assert "--model" in args
        assert "sonnet" in args

    def test_with_max_turns(self):
        args = _build_command("hello", max_turns=5)
        assert "--max-turns" in args
        assert "5" in args

    def test_with_reasoning_effort(self):
        args = _build_command("hello", reasoning_effort="high")
        assert "--effort" in args
        assert "high" in args


class TestClaudeCLIBackend:
    async def test_success(self, tmp_path: Path):
        backend = ClaudeCLIBackend()
        with patch(_CLAUDE_RUN, new_callable=AsyncMock) as mock:
            mock.return_value = (0, "Review output here", "")
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "ok"
        assert result.output == "Review output here"

    async def test_nonzero_exit(self, tmp_path: Path):
        backend = ClaudeCLIBackend()
        with patch(_CLAUDE_RUN, new_callable=AsyncMock) as mock:
            mock.return_value = (1, "", "something broke")
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "error"
        assert "exited with status 1" in result.error

    async def test_empty_output(self, tmp_path: Path):
        backend = ClaudeCLIBackend()
        with patch(_CLAUDE_RUN, new_callable=AsyncMock) as mock:
            mock.return_value = (0, "   ", "")
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "error"
        assert "empty response" in result.error

    async def test_timeout(self, tmp_path: Path):
        backend = ClaudeCLIBackend()
        with patch(_CLAUDE_RUN, new_callable=AsyncMock) as mock:
            mock.side_effect = TimeoutError
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=10,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "error"
        assert "timed out" in result.error


# --- codex_cli helpers ---


class TestCodexSanitizeOutput:
    def test_empty(self):
        assert _sanitize_output("") == ""

    def test_strips_warning_lines(self):
        text = "Failed to write last message file /tmp/foo\nReal output"
        assert _sanitize_output(text) == "Real output"

    def test_passes_normal_text(self):
        assert _sanitize_output("Hello world") == "Hello world"


class TestCodexExtractFallback:
    def test_from_stdout(self):
        assert _extract_fallback_text("stdout text", "") == "stdout text"

    def test_from_stderr_marker(self):
        stderr = "junk\ncodex\nThe review output"
        assert _extract_fallback_text("", stderr) == "The review output"

    def test_empty(self):
        assert _extract_fallback_text("", "") == ""


class TestCodexCLIBackend:
    async def test_success_from_output_file(self, tmp_path: Path):
        backend = CodexCLIBackend()

        async def fake_run(args, *, cwd, timeout):
            # Simulate codex writing the output file
            for a in args:
                if str(a).startswith(str(tmp_path)) and str(a).endswith(".md"):
                    Path(a).write_text("codex result", encoding="utf-8")
                    break
            return (0, "", "")

        with patch("autopilot.backends.codex_cli.run_command_async", side_effect=fake_run):
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "ok"
        assert result.output == "codex result"

    async def test_timeout(self, tmp_path: Path):
        backend = CodexCLIBackend()
        with patch(_CODEX_RUN, new_callable=AsyncMock) as mock:
            mock.side_effect = TimeoutError
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=10,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "error"
        assert "timed out" in result.error


# --- gemini_cli helpers ---


class TestGeminiExtractMarkdownFromPayload:
    def test_direct_response_key(self):
        assert _extract_markdown_from_payload({"response": "hello"}) == "hello"

    def test_parts_key(self):
        payload = {"parts": [{"text": "part1"}, {"text": "part2"}]}
        assert _extract_markdown_from_payload(payload) == "part1\npart2"

    def test_non_dict(self):
        assert _extract_markdown_from_payload("not a dict") == ""

    def test_empty_values(self):
        assert _extract_markdown_from_payload({"response": "  "}) == ""


class TestGeminiIterJsonPayloads:
    def test_single(self):
        payloads = _iter_json_payloads('{"key": "val"}')
        assert len(payloads) == 1
        assert payloads[0]["key"] == "val"

    def test_multiple(self):
        text = '{"a": 1} some garbage {"b": 2}'
        payloads = _iter_json_payloads(text)
        assert len(payloads) == 2

    def test_empty(self):
        assert _iter_json_payloads("no json here") == []


class TestGeminiExtractText:
    def test_from_json(self):
        stdout = '{"response": "found bugs"}'
        assert _extract_text(stdout, "") == "found bugs"

    def test_from_plain_stdout(self):
        assert _extract_text("plain output", "") == "plain output"

    def test_from_stderr_marker(self):
        stderr = "info\ngemini\nThe result"
        assert _extract_text("", stderr) == "The result"

    def test_empty(self):
        assert _extract_text("", "") == ""


class TestGeminiSummarizeError:
    def test_extracts_error_line(self):
        stderr = "stack trace\nTypeError: something broke\n  at foo.js:1"
        assert "TypeError: something broke" in _summarize_error(stderr)

    def test_fallback_first_line(self):
        assert _summarize_error("just a message") == "just a message"

    def test_truncates_long(self):
        long = "x" * 300
        assert len(_summarize_error(long)) <= 200


class TestGeminiCLIBackend:
    async def test_success(self, tmp_path: Path):
        backend = GeminiCLIBackend()
        with patch(_GEMINI_RUN, new_callable=AsyncMock) as mock:
            mock.return_value = (0, '{"response": "all good"}', "")
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "ok"
        assert result.output == "all good"

    async def test_nonzero_exit(self, tmp_path: Path):
        backend = GeminiCLIBackend()
        with patch(_GEMINI_RUN, new_callable=AsyncMock) as mock:
            mock.return_value = (1, "", "FatalError: quota exceeded")
            result = await backend.run(
                "scan", cwd=tmp_path, timeout_seconds=60,
                model=None, reasoning_effort=None, skip_permissions=True, max_turns=5,
            )
        assert result.status == "error"


# --- openai_agents_sdk helpers ---


class TestExtractResultText:
    def test_from_object_attr(self):
        class R:
            final_output = "the output"
        assert _extract_result_text(R()) == "the output"

    def test_from_dict(self):
        assert _extract_result_text({"output": "dict output"}) == "dict output"

    def test_from_string(self):
        assert _extract_result_text("plain string") == "plain string"

    def test_empty(self):
        assert _extract_result_text({}) == ""

    def test_prefers_final_output(self):
        class R:
            final_output = "preferred"
            output = "fallback"
        assert _extract_result_text(R()) == "preferred"
