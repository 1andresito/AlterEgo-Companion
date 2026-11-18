"""AI providers: the things that actually generate text.

Every provider implements the Provider interface in base.py. The rest of the
app only talks to that interface, so adding a new backend means adding one
file here and one entry to the registry below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.tools import Access, ToolBox, default_folder
from ..settings.config import Config, data_dir, program_dir
from .base import ChatMessage, Provider, ProviderError
from .claude_code import ClaudeCodeProvider
from .ollama import OllamaProvider
from .ollama_server import ollama_server
from .openai_compat import OpenAICompatibleProvider

OFFLINE_ID = "offline"

# provider id -> label shown in menus. "offline" is the built-in rule-based responder.
PROVIDER_LABELS: dict[str, str] = {
    OFFLINE_ID: "Offline (no AI)",
    OllamaProvider.id: OllamaProvider.label,
    ClaudeCodeProvider.id: ClaudeCodeProvider.label,
    OpenAICompatibleProvider.id: OpenAICompatibleProvider.label,
}


def tools_folder(config: Config) -> Path:
    """The AI's own folder: where new files go when no full path is given."""
    custom = str(config.get("tools", "folder", "") or "")
    return Path(custom).expanduser() if custom else default_folder()


def protected_folders() -> list[Path]:
    """Alter Ego's own folders: auto-edit still asks before changing anything in them."""
    return [data_dir(), program_dir()]


def build_toolbox(config: Config, approve: Callable[[Access], bool] | None = None,
                  story: Callable[[str], bool] | None = None) -> ToolBox:
    """The tools the user allowed in the AI menu. `approve` is asked before file changes; `story`
    tells which messages are about Alter Ego's story (Knowledge.mentions), so they don't go online."""
    return ToolBox(
        folder=tools_folder(config),
        internet=bool(config.get("tools", "internet", True)),
        files=bool(config.get("tools", "files", True)),
        approve=approve or (lambda _access: False),  # Nobody to ask means no changes.
        search_url=str(config.get("tools", "search_url", "") or ""),
        auto_edit=bool(config.get("tools", "auto_edit", False)),
        protected=protected_folders(),
        story=story,
    )


def create_provider(
    provider_id: str,
    config: Config,
    approve: Callable[[Access], bool] | None = None,
    approval_address: str = "",
    story: Callable[[str], bool] | None = None,
) -> Provider | None:
    """Build the provider named in the config. Returns None for offline mode.

    `approve` (Ollama) and `approval_address` (Claude Code's tool server, see
    tools_mcp.py) are how the user is asked before the AI changes a file.
    """
    tools = build_toolbox(config, approve, story)
    if provider_id == OllamaProvider.id:
        return OllamaProvider(
            base_url=str(config.get("ollama", "base_url", "http://localhost:11434")),
            command=str(config.get("ollama", "command", "ollama") or "ollama"),
            auto_start=bool(config.get("ollama", "auto_start", True)),
            auto_pull=bool(config.get("ollama", "auto_pull", False)),
            default_model=str(config.get("ollama", "default_model", "") or ""),
            tools=tools,
        )
    if provider_id == ClaudeCodeProvider.id:
        working_dir = data_dir() / "claude_code"
        return ClaudeCodeProvider(
            command=str(config.get("claude_code", "command", "claude") or "claude"),
            working_dir=working_dir,
            effort=str(config.get("claude_code", "effort", "") or ""),
            # Resume the same Claude Code session after a restart, but only while memory is on.
            session_file=working_dir / "session" if config.memory_enabled else None,
            internet=tools.internet,
            # File tools need someone to approve changes; without the app's approval server they stay off.
            files_folder=tools.folder if tools.files and approval_address else None,
            approval_address=approval_address,
            auto_edit=tools.auto_edit,
            protected=protected_folders(),
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
    "build_toolbox",
    "tools_folder",
    "Provider",
    "ProviderError",
    "create_provider",
    "ollama_server",
]
