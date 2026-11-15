"""Claude through the Claude Code CLI: uses the user's existing Claude login, no API key.

Claude Code (https://claude.com/claude-code) has a non-interactive "print"
mode: `claude -p "<prompt>"` answers once and exits. With
`--output-format stream-json` it writes one JSON object per line, including
text deltas as they are generated. This provider runs that command with
Alter Ego's personality as the system prompt and all tools switched off, so
it is a pure chat and cannot touch the user's files.

Conversation memory: the first message starts a session with a fresh UUID
(`--session-id`); later messages pass `--resume <uuid>` so Claude Code keeps
the context itself. Clearing the chat starts a new session.

Requirements: Claude Code installed and logged in (run `claude` once in a
terminal and use /login). Whether a Claude subscription may be used this way
for a third-party app is governed by Anthropic's terms; see the README.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable, Iterator, Sequence

from .base import ChatMessage, Provider, ProviderError

DEFAULT_COMMAND = "claude"
# Model aliases Claude Code understands. "default" means: whatever Claude Code is set to.
MODELS = ["default", "opus", "sonnet", "haiku"]
VERSION_TIMEOUT_S = 30
REPLY_TIMEOUT_S = 300
INSTALL_HINT = "Install Claude Code from https://claude.com/claude-code, then run `claude` once and use /login."


class ClaudeCodeProvider(Provider):
    id = "claude_code"
    label = "Claude (via Claude Code login, no API key)"

    def __init__(
        self,
        command: str | Sequence[str] = DEFAULT_COMMAND,
        working_dir: Path | None = None,
        effort: str = "",
    ):
        # `command` is normally "claude"; tests pass a list such as [python, fake_script].
        self._command = list(command) if not isinstance(command, str) else command
        self._working_dir = working_dir
        self._effort = effort
        self._session_id: str | None = None

    # ----- Provider interface -----

    def describe(self) -> str:
        name = self._command if isinstance(self._command, str) else Path(self._command[-1]).name
        return f"Claude Code CLI ({name})"

    def list_models(self) -> list[str]:
        return list(MODELS)

    def test_connection(self) -> str:
        output = self._run_simple(["--version"], timeout=VERSION_TIMEOUT_S)
        version = output.strip().splitlines()[0] if output.strip() else "unknown version"
        return (
            f"Claude Code is installed ({version}). I'll talk through your Claude login; "
            "if I say you're not logged in, run `claude` in a terminal and type /login."
        )

    def reset(self) -> None:
        """Forget the current Claude Code session (called when the chat is cleared)."""
        self._session_id = None

    def stream_reply(
        self,
        messages: list[ChatMessage],
        model: str,
        cancelled: Callable[[], bool],
    ) -> Iterator[str]:
        system_prompt = "\n\n".join(m.content for m in messages if m.role == "system")
        prompt = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if not prompt:
            return

        resuming = self._session_id is not None
        session_id = self._session_id or str(uuid.uuid4())
        try:
            yield from self._stream_once(prompt, system_prompt, model, session_id, resuming, cancelled)
        except ProviderError:
            self._session_id = None
            if not resuming:
                raise
            # The old session may have been deleted or compacted away; start a fresh one.
            session_id = str(uuid.uuid4())
            yield from self._stream_once(prompt, system_prompt, model, session_id, False, cancelled)

    # ----- Running the CLI -----

    def _base_args(self) -> list[str]:
        if isinstance(self._command, str):
            resolved = _resolve_executable(self._command)
            if resolved is None:
                raise ProviderError(f"I can't find the `{self._command}` command. {INSTALL_HINT}")
            if resolved.lower().endswith((".cmd", ".bat")):
                return ["cmd", "/c", resolved]  # Batch wrappers (npm installs) need cmd.exe.
            return [resolved]
        return list(self._command)

    def _reply_args(self, prompt: str, system_prompt: str, model: str, session_id: str, resuming: bool) -> list[str]:
        args = self._base_args() + [
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",                  # required by stream-json in print mode
            "--include-partial-messages",  # text deltas as they are generated
            "--tools", "",                # pure chat: no file, shell or web tools
            "--max-turns", "1",
            "--disable-slash-commands",
            "--setting-sources", "",      # ignore the user's coding hooks/plugins
            "--system-prompt", system_prompt,
        ]
        if model and model != "default":
            args += ["--model", model]
        if self._effort:
            args += ["--effort", self._effort]
        args += ["--resume", session_id] if resuming else ["--session-id", session_id]
        return args

    def _popen(self, args: list[str]) -> subprocess.Popen:
        env = os.environ.copy()
        # Claude Code refuses to start inside another Claude Code session; these mark one.
        env.pop("CLAUDECODE", None)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # no console flashing up
        if self._working_dir is not None:
            self._working_dir.mkdir(parents=True, exist_ok=True)
        try:
            return subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(self._working_dir) if self._working_dir else None,
                env=env,
                encoding="utf-8",
                errors="replace",
                **kwargs,
            )
        except FileNotFoundError:
            raise ProviderError(f"I can't run `{args[0]}`. {INSTALL_HINT}") from None
        except OSError as error:
            raise ProviderError(f"I couldn't start Claude Code: {error}") from None

    def _run_simple(self, extra_args: list[str], timeout: float) -> str:
        process = self._popen(self._base_args() + extra_args)
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise ProviderError("Claude Code took too long to answer.") from None
        if process.returncode != 0:
            raise ProviderError(f"Claude Code exited with code {process.returncode}: {output.strip()[:200]}")
        return output

    def _stream_once(self, prompt, system_prompt, model, session_id, resuming, cancelled) -> Iterator[str]:
        process = self._popen(self._reply_args(prompt, system_prompt, model, session_id, resuming))
        stop_watchdog = threading.Event()

        def watchdog() -> None:
            # Kills the CLI if the user cancels or it runs far too long; stdout then ends.
            waited = 0.0
            while not stop_watchdog.wait(0.1):
                waited += 0.1
                if cancelled() or waited > REPLY_TIMEOUT_S:
                    process.kill()
                    return

        threading.Thread(target=watchdog, daemon=True).start()

        streamed_any = False
        result: dict | None = None
        noise: list[str] = []  # Non-JSON output, shown if things go wrong.
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if cancelled():
                    process.kill()
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    noise.append(line)
                    continue
                kind = event.get("type")
                if kind == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        streamed_any = True
                        yield delta["text"]
                elif kind == "result":
                    result = event
        finally:
            stop_watchdog.set()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()

        if cancelled():
            return
        if result is None or result.get("is_error") or process.returncode != 0:
            raise ProviderError(_explain_failure(result, process.returncode, noise))
        if not streamed_any and result.get("result"):
            yield str(result["result"])  # Older CLI without deltas: the whole reply at once.
        self._session_id = session_id


def _resolve_executable(command: str) -> str | None:
    found = shutil.which(command)
    if found is None and sys.platform == "win32":
        for suffix in (".exe", ".cmd"):
            found = shutil.which(command + suffix)
            if found:
                break
    return found


def _explain_failure(result: dict | None, returncode: int | None, noise: list[str]) -> str:
    detail = ""
    if result is not None:
        detail = str(result.get("result") or result.get("error") or "").strip()
    if not detail and noise:
        detail = noise[-1][:200]
    lowered = detail.lower()
    if "not logged in" in lowered or "login" in lowered or "authentication" in lowered:
        return "Claude Code says I'm not logged in. Open a terminal, run `claude`, and type /login."
    if "rate limit" in lowered or "usage limit" in lowered:
        return f"Claude Code hit a usage limit: {detail}"
    if detail:
        return f"Claude Code couldn't answer: {detail}"
    return f"Claude Code exited with code {returncode} without a reply."
