"""Alter Ego's file tools for Claude Code, as a tiny MCP server.

Claude Code runs tools from "MCP servers": programs it starts and talks to with
JSON-RPC, one JSON object per line on stdin/stdout. This module is such a
server for the file tools in core/tools.py, so Claude works with files the
same way Ollama does, with the same questions. Claude's own web tools
(WebSearch, WebFetch) cover the internet, so only file tools are served here.

    Claude Code --stdin/stdout--> tools_mcp (this file, a separate process)
                                     │  a change, or a read outside the Alter Ego folder?
                                     ▼
                       ApprovalServer in Alter Ego (127.0.0.1, random port + token)
                                     │
                                     ▼
                     "Can I change <path>?"  Yes / No

The server process is Alter Ego itself started with `--tool-server` (see
main.py), so it also works from a packaged build. The approval address and a
one-time token are passed in environment variables; a connection without the
token is ignored.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
from pathlib import Path
from typing import Callable

from ..core.tools import ACCESS_KINDS, FILE_TOOLS, PREVIEW_CHARS, Access, ToolBox

SERVER_NAME = "alter_ego"           # Claude Code names the tools mcp__alter_ego__<tool>.
APPROVAL_ENV = "ALTER_EGO_APPROVAL"  # "port:token" of the app's ApprovalServer
FOLDER_ENV = "ALTER_EGO_FOLDER"     # Where bare file names go
AUTO_EDIT_ENV = "ALTER_EGO_AUTO_EDIT"  # "1" = change files without asking (AI -> Edit files without asking)
PROTECTED_ENV = "ALTER_EGO_PROTECTED"  # Alter Ego's own folders, os.pathsep-separated: auto-edit asks there anyway
TOOL_SERVER_FLAG = "--tool-server"
APPROVAL_TIMEOUT_S = 180            # How long a question may stay unanswered before it counts as "no".
PROTOCOL_VERSION = "2025-06-18"     # Used only if the client does not say which version it speaks.


def tool_server_command() -> list[str]:
    """The command line that starts this server: Alter Ego's own executable or main.py."""
    if getattr(sys, "frozen", False):
        return [sys.executable, TOOL_SERVER_FLAG]
    main = Path(__file__).resolve().parents[3] / "main.py"
    return [sys.executable, str(main), TOOL_SERVER_FLAG]


# ----- In the app: answering approval questions -----

class ApprovalServer:
    """Listens on 127.0.0.1 for "may I do this?" from the tool server and asks `approve`."""

    def __init__(self, approve: Callable[[Access], bool]):
        self._approve = approve
        self.token = secrets.token_hex(16)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        self.port = self._socket.getsockname()[1]
        self._closed = False
        threading.Thread(target=self._serve, name="approval-server", daemon=True).start()

    @property
    def address(self) -> str:
        return f"{self.port}:{self.token}"

    def close(self) -> None:
        self._closed = True
        try:
            self._socket.close()
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._closed:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return  # Closed on quit.
            threading.Thread(target=self._answer, args=(connection,), daemon=True).start()

    def _answer(self, connection: socket.socket) -> None:
        with connection:
            try:
                connection.settimeout(APPROVAL_TIMEOUT_S + 10)
                request = json.loads(connection.makefile("r", encoding="utf-8").readline() or "{}")
                if not secrets.compare_digest(str(request.get("token", "")), self.token):
                    return
                kind, path = str(request.get("kind", "")), str(request.get("path", ""))
                allowed = False
                if kind in ACCESS_KINDS and path:  # Anything malformed is a no, without asking.
                    detail = str(request.get("detail", ""))[:PREVIEW_CHARS + 50]
                    allowed = bool(self._approve(Access(kind, Path(path), detail)))
                connection.sendall((json.dumps({"ok": allowed}) + "\n").encode("utf-8"))
            except (OSError, ValueError):
                pass


def ask_app(address: str, access: Access) -> bool:
    """In the tool server: ask the app whether this may happen. Any failure means no."""
    port, _, token = address.partition(":")
    request = {"token": token, "kind": access.kind, "path": str(access.path), "detail": access.detail}
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=5) as connection:
            connection.settimeout(APPROVAL_TIMEOUT_S + 5)
            connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
            answer = json.loads(connection.makefile("r", encoding="utf-8").readline() or "{}")
            return bool(answer.get("ok"))
    except (OSError, ValueError):
        return False


# ----- In the tool server process: the MCP side -----

def handle(request: dict, tools: ToolBox) -> dict | None:
    """Answer one JSON-RPC message. Returns None for notifications, which get no answer."""
    method = request.get("method")
    if "id" not in request:
        return None
    reply: dict = {"jsonrpc": "2.0", "id": request["id"]}
    params = request.get("params") or {}
    if method == "initialize":
        reply["result"] = {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1"},
        }
    elif method == "tools/list":
        reply["result"] = {"tools": [
            {"name": spec["function"]["name"], "description": spec["function"]["description"],
             "inputSchema": spec["function"]["parameters"]}
            for spec in FILE_TOOLS
        ]}
    elif method == "tools/call":
        text = tools.run(str(params.get("name", "")), params.get("arguments") or {})
        reply["result"] = {"content": [{"type": "text", "text": text}], "isError": text.startswith("Error:")}
    elif method == "ping":
        reply["result"] = {}
    else:
        reply["error"] = {"code": -32601, "message": f"Unknown method {method}"}
    return reply


def main() -> int:
    """Serve the file tools on stdin/stdout until Claude Code closes the pipe."""
    address = os.environ.get(APPROVAL_ENV, "")
    folder = os.environ.get(FOLDER_ENV) or None
    protected = [p for p in os.environ.get(PROTECTED_ENV, "").split(os.pathsep) if p]
    tools = ToolBox(folder=folder, internet=False, files=True,
                    approve=(lambda access: ask_app(address, access)) if address else (lambda access: False),
                    auto_edit=os.environ.get(AUTO_EDIT_ENV) == "1", protected=protected)
    # File descriptors 0 and 1, not sys.stdin/sys.stdout: in the packaged (windowed) build Python sets
    # those to None because there is no console, yet the pipes Claude Code passed are there.
    stdin = open(0, "r", encoding="utf-8", closefd=False)
    stdout = open(1, "w", encoding="utf-8", closefd=False, newline="\n")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        reply = handle(request, tools)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0
