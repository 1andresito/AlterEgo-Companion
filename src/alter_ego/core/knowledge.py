"""What Alter Ego knows about its own story (Danganronpa), chosen per message.

The facts live in assets/personality/knowledge.json:

    "core":   always in the system prompt: only who Alter Ego is, so the story never
              comes up in everyday chat
    "topics": [{"keywords": [...], "text": "..."}]  added when a keyword is in what
              the user just said, at most MAX_TOPICS at a time

Small local models have little room (Ollama is asked for 8K tokens of context, see
providers/ollama.py) and get confused by long prompts, so the whole file is never
sent at once: only the core, plus the topics the conversation is about. Standard
library only; a missing or broken file just means no extra knowledge.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

MAX_TOPICS = 3


@dataclass(frozen=True)
class Topic:
    keywords: tuple[str, ...]
    text: str

    def score(self, text: str) -> int:
        """How many of the keywords appear in `text` as whole words (any case)."""
        return sum(1 for keyword in self.keywords if _contains(text, keyword))


@dataclass(frozen=True)
class Knowledge:
    core: str = ""
    topics: tuple[Topic, ...] = field(default_factory=tuple)

    @classmethod
    def load(cls, path: Path) -> Knowledge:
        """Read a knowledge file. Returns empty knowledge on any problem (reported with print())."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"Warning: knowledge file not found: {path}. Alter Ego knows only its personality.")
            return cls()
        except (OSError, json.JSONDecodeError) as error:
            print(f"Warning: could not read knowledge file {path}: {error}.")
            return cls()
        if not isinstance(data, dict):
            return cls()
        core = data.get("core", "")
        if isinstance(core, list):
            core = "\n".join(str(line) for line in core)
        topics = []
        for entry in data.get("topics", []) if isinstance(data.get("topics"), list) else []:
            if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
                continue
            keywords = tuple(str(k).lower().strip() for k in entry.get("keywords", []) if str(k).strip())
            if keywords:
                topics.append(Topic(keywords, str(entry["text"]).strip()))
        return cls(str(core).strip(), tuple(topics))

    def mentions(self, text: str) -> bool:
        """Does `text` name something from the story (a topic keyword)? Such questions are answered
        from this knowledge, not looked up online (see core/tools.py wants_web)."""
        return any(topic.score(text) for topic in self.topics)

    def prompt_for(self, recent: Sequence[str]) -> str:
        """The core, plus the topics the user's recent messages are about (latest first in weight)."""
        if not self.core and not self.topics:
            return ""
        scored: list[tuple[int, int, Topic]] = []
        for index, topic in enumerate(self.topics):
            # The latest message counts double, so a new subject wins over the previous one.
            score = sum(topic.score(text) * (2 if i == len(recent) - 1 else 1) for i, text in enumerate(recent))
            if score:
                scored.append((-score, index, topic))
        chosen = [topic.text for _, _, topic in sorted(scored)[:MAX_TOPICS]]
        parts = [self.core] if self.core else []
        if chosen:
            parts.append("What you remember about this:\n" + "\n".join(chosen))
        return "\n\n".join(parts)


def _contains(text: str, keyword: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text, re.IGNORECASE) is not None
