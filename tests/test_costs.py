from __future__ import annotations

import pytest

from autopilot.costs import parse_costs
from autopilot.models import TokenUsage


class TestParseCosts:
    def test_claude_cli_output(self):
        output = "Found 3 issues.\n\n1,234 input tokens, 567 output tokens\nTotal cost: $0.02\n"
        usage = parse_costs("claude_cli", output)
        assert usage is not None
        assert usage.tokens_in == 1234
        assert usage.tokens_out == 567
        assert usage.cost_usd == pytest.approx(0.02)

    def test_claude_sdk_output(self):
        output = "Result text here.\n\n2,000 input tokens, 800 output tokens\nTotal cost: $0.05\n"
        usage = parse_costs("claude_sdk", output)
        assert usage is not None
        assert usage.tokens_in == 2000
        assert usage.tokens_out == 800

    def test_codex_cli_output(self):
        output = "Done.\n500 in tokens, 200 out tokens\nCost: $0.01\n"
        usage = parse_costs("codex_cli", output)
        assert usage is not None
        assert usage.tokens_in == 500
        assert usage.tokens_out == 200
        assert usage.cost_usd == pytest.approx(0.01)

    def test_no_token_info_returns_none(self):
        usage = parse_costs("claude_cli", "Just some output with no token info.")
        assert usage is None

    def test_ignores_prose_dollar_amounts(self):
        usage = parse_costs("claude_cli", "This saved $500 and processed 200 input files.")
        assert usage is None

    def test_empty_output(self):
        usage = parse_costs("claude_cli", "")
        assert usage is None

    def test_unknown_backend(self):
        usage = parse_costs("unknown_backend", "tokens: 100")
        assert usage is None


class TestTokenUsage:
    def test_defaults(self):
        usage = TokenUsage()
        assert usage.tokens_in is None
        assert usage.tokens_out is None
        assert usage.cost_usd is None

    def test_with_values(self):
        usage = TokenUsage(tokens_in=100, tokens_out=50, cost_usd=0.01)
        assert usage.tokens_in == 100
        assert usage.tokens_out == 50
        assert usage.cost_usd == 0.01
