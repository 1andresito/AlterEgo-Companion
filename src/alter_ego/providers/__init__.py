"""AI providers: the things that actually generate text.

Every provider implements the Provider interface in base.py. The rest of the
app only talks to that interface, so adding a new backend means adding one
file here and one line to the registry below.
"""

from __future__ import annotations

from ..settings.config import Config
from .base import ChatMessage, Provider, ProviderError
from .ollama import OllamaProvider

OFFLINE_ID = "offline"

# provider id -> label shown in menus. "offline" is the built-in rule-based responder.
PROVIDER_LABELS: dict[str, str] = {
    OFFLINE_ID: "Offline (no AI)",
    OllamaProvider.id: OllamaProvider.label,
}


def create_provider(provider_id: str, config: Config) -> Provider | None:
    """Build the provider named in the config. Returns None for offline mode."""
    if provider_id == OllamaProvider.id:
        return OllamaProvider(base_url=str(config.get("ollama", "base_url", "http://localhost:11434")))
    if provider_id != OFFLINE_ID:
        print(f"Warning: unknown provider '{provider_id}' in settings. Using offline mode.")
    return None


__all__ = [
    "ChatMessage",
    "OFFLINE_ID",
    "OllamaProvider",
    "PROVIDER_LABELS",
    "Provider",
    "ProviderError",
    "create_provider",
]
