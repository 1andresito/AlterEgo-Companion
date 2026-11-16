"""AI providers: the things that actually generate text.

Every provider implements the Provider interface in base.py. The rest of the
app only talks to that interface, so adding a new backend means adding one
file here and one entry to the registry below.
"""

from __future__ import annotations

from ..settings.config import Config, data_dir
from .base import ChatMessage, Provider, ProviderError
from .claude_code import ClaudeCodeProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatibleProvider

OFFLINE_ID = "offline"

# provider id -> label shown in menus. "offline" is the built-in rule-based responder.
PROVIDER_LABELS: dict[str, str] = {
    OFFLINE_ID: "Offline (no AI)",
    OllamaProvider.id: OllamaProvider.label,
    ClaudeCodeProvider.id: ClaudeCodeProvider.label,
    OpenAICompatibleProvider.id: OpenAICompatibleProvider.label,
}


def create_provider(provider_id: str, config: Config) -> Provider | None:
    """Build the provider named in the config. Returns None for offline mode."""
    if provider_id == OllamaProvider.id:
        return OllamaProvider(base_url=str(config.get("ollama", "base_url", "http://localhost:11434")))
    if provider_id == ClaudeCodeProvider.id:
        working_dir = data_dir() / "claude_code"
        return ClaudeCodeProvider(
            command=str(config.get("claude_code", "command", "claude") or "claude"),
            working_dir=working_dir,
            effort=str(config.get("claude_code", "effort", "") or ""),
            # Resume the same Claude Code session after a restart, but only while memory is on.
            session_file=working_dir / "session" if config.memory_enabled else None,
        )
    if provider_id == OpenAICompatibleProvider.id:
        return OpenAICompatibleProvider(
            base_url=str(config.get("openai", "base_url", "https://api.openai.com/v1")),
            api_key=str(config.get("openai", "api_key", "") or ""),
        )
    if provider_id != OFFLINE_ID:
        print(f"Warning: unknown provider '{provider_id}' in settings. Using offline mode.")
    return None


__all__ = [
    "ChatMessage",
    "ClaudeCodeProvider",
    "OFFLINE_ID",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "PROVIDER_LABELS",
    "Provider",
    "ProviderError",
    "create_provider",
]
