"""A stand-in for the `claude` command, used by tests.

It imitates `claude -p --output-format stream-json` closely enough for the
provider: an init line, text deltas, an assistant message and a result line.
Behaviour is steered by the prompt text:

  "fail-auth"   -> the "Not logged in" error shape
  "fail-resume" -> errors when --resume is given (simulates a lost session)
  "tool-mid"    -> some words, then a web search, then more words
  anything else -> streams "[happy] You said: <prompt>" and echoes the flags
"""

from __future__ import annotations

import json
import sys


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    if "--version" in argv:
        print("9.9.9 (Claude Code fake)")
        return 0

    def flag(name: str) -> str | None:
        return argv[argv.index(name) + 1] if name in argv else None

    prompt = flag("-p") or ""
    session_id = flag("--session-id") or flag("--resume") or "no-session"
    resuming = "--resume" in argv
    emit({"type": "system", "subtype": "init", "session_id": session_id, "tools": [], "model": flag("--model") or "default"})

    if "fail-auth" in prompt or (resuming and "fail-resume" in prompt):
        text = "Not logged in · Please run /login" if "fail-auth" in prompt else "No conversation found with session ID"
        emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}, "error": "failed"})
        emit({"type": "result", "subtype": "success", "is_error": True, "result": text, "session_id": session_id})
        return 1

    if "tool-mid" in prompt:
        def delta(text: str) -> None:
            emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                                    "delta": {"type": "text_delta", "text": text}}})
        delta("[happy] Let me look.")
        emit({"type": "stream_event", "event": {"type": "content_block_start",
                                                "content_block": {"type": "tool_use", "name": "WebSearch"}}})
        delta(" Found it!")
        emit({"type": "result", "subtype": "success", "is_error": False, "result": "", "session_id": session_id})
        return 0

    reply = f"[happy] You said: {prompt}"
    if "--system-prompt" in argv:
        reply += f" | system={len(flag('--system-prompt') or '')}"
    reply += f" | resumed={resuming} | model={flag('--model') or 'default'} | tools={flag('--tools')!r}"
    for start in range(0, len(reply), 7):
        emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                                "delta": {"type": "text_delta", "text": reply[start:start + 7]}}})
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": reply, "session_id": session_id})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
