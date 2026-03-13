from __future__ import annotations

from ai_automations.backends.base import Backend


def get_backend(backend_type: str) -> Backend:
    """Return a backend instance for the given type string."""
    match backend_type:
        case "claude_cli":
            from ai_automations.backends.claude_cli import ClaudeCLIBackend

            return ClaudeCLIBackend()
        case "claude_sdk":
            from ai_automations.backends.claude_sdk import ClaudeSDKBackend

            return ClaudeSDKBackend()
        case "codex_cli":
            from ai_automations.backends.codex_cli import CodexCLIBackend

            return CodexCLIBackend()
        case "openai_agents_sdk":
            from ai_automations.backends.openai_agents_sdk import OpenAIAgentsSDKBackend

            return OpenAIAgentsSDKBackend()
        case "gemini_cli":
            from ai_automations.backends.gemini_cli import GeminiCLIBackend

            return GeminiCLIBackend()
        case _:
            raise ValueError(f"Unknown backend: {backend_type!r}")


__all__ = ["Backend", "get_backend"]
