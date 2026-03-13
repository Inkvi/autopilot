from __future__ import annotations

import re
from collections.abc import Callable

from autopilot.models import TokenUsage

# Patterns for extracting token counts and costs from backend output.
_TOKENS_IN_RE = re.compile(r"([\d,]+)\s*(?:input|in)\b", re.IGNORECASE)
_TOKENS_OUT_RE = re.compile(r"([\d,]+)\s*(?:output|out)\b", re.IGNORECASE)
_COST_RE = re.compile(r"\$\s*([\d,.]+)")


def _parse_int(s: str) -> int:
    return int(s.replace(",", ""))


def _generic_parse(output: str) -> TokenUsage | None:
    """Try to extract token counts and cost from output using common patterns."""
    tokens_in_match = _TOKENS_IN_RE.search(output)
    tokens_out_match = _TOKENS_OUT_RE.search(output)
    cost_match = _COST_RE.search(output)

    if not tokens_in_match and not tokens_out_match and not cost_match:
        return None

    return TokenUsage(
        tokens_in=_parse_int(tokens_in_match.group(1)) if tokens_in_match else None,
        tokens_out=_parse_int(tokens_out_match.group(1)) if tokens_out_match else None,
        cost_usd=float(cost_match.group(1).replace(",", "")) if cost_match else None,
    )


_BACKEND_PARSERS: dict[str, Callable[[str], TokenUsage | None]] = {
    "claude_cli": _generic_parse,
    "claude_sdk": _generic_parse,
    "codex_cli": _generic_parse,
    "gemini_cli": _generic_parse,
    "openai_agents_sdk": _generic_parse,
}


def parse_costs(backend: str, output: str) -> TokenUsage | None:
    """Parse token usage and cost from backend output. Returns None if not parseable."""
    parser = _BACKEND_PARSERS.get(backend)
    if parser is None:
        return None
    if not output:
        return None
    return parser(output)
