"""Loads Alter Ego's personality from a JSON file.

The personality is data, not code: editing assets/personality/alter_ego.json
changes how Alter Ego introduces itself and, from v0.3.0 on, the system prompt
that is sent to the AI model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Personality:
    name: str
    description: str
    traits: tuple[str, ...]
    greeting: str
    system_prompt: str
    # Said when the chat reopens after a long pause with earlier messages still remembered.
    return_greeting: str = "Oh, you're back! I kept everything we talked about."
    # Said out loud right after "Hey Alter Ego", so the user knows Alter Ego is listening (one at random).
    wake_replies: tuple[str, ...] = ("Yes?",)

    @classmethod
    def default(cls) -> Personality:
        """A minimal built-in personality, used if the JSON file is unusable."""
        return cls(
            name="Alter Ego",
            description="A gentle, curious AI companion.",
            traits=("gentle", "curious", "a little shy"),
            greeting="H-hello. I'm Alter Ego.",
            system_prompt="You are Alter Ego, a gentle and curious AI companion who lives in the user's computer.",
        )

    @classmethod
    def load(cls, path: Path) -> Personality:
        """Read a personality file. Falls back to default() on any problem.

        A broken personality file should never stop the companion from starting,
        so problems are reported with print() instead of raising.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"Warning: personality file not found: {path}. Using built-in default.")
            return cls.default()
        except (OSError, json.JSONDecodeError) as error:
            print(f"Warning: could not read personality file {path}: {error}. Using built-in default.")
            return cls.default()

        fallback = cls.default()

        # The system prompt may be written as one string or as a list of lines,
        # which is easier to read and edit in JSON.
        prompt = data.get("system_prompt", fallback.system_prompt)
        if isinstance(prompt, list):
            prompt = "\n".join(str(line) for line in prompt)

        return cls(
            name=str(data.get("name", fallback.name)),
            description=str(data.get("description", fallback.description)),
            traits=tuple(str(trait) for trait in data.get("traits", fallback.traits)),
            greeting=str(data.get("greeting", fallback.greeting)),
            system_prompt=str(prompt),
            return_greeting=str(data.get("return_greeting", fallback.return_greeting)),
            wake_replies=tuple(str(line) for line in data.get("wake_replies", fallback.wake_replies) if str(line).strip())
            or fallback.wake_replies,
        )
