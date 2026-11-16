"""Recognising the wake phrase ("Hey Alter Ego") in a transcript.

Whisper hears "Alter Ego" as "alter ego", "Altar Ego", "alterego" or
"Alta ego" depending on the voice and the model size, so the comparison is
fuzzy: the phrase (with or without its leading "hey") is compared with the
first few words of what was said, and anything after it is the command.
"""

from __future__ import annotations

import difflib
import re

DEFAULT_PHRASE = "hey alter ego"
WORD_RATIO = 0.7     # "altar" ~ "alter", "alta" ~ "alter"
JOINED_RATIO = 0.85  # "alterego" ~ "alter ego" (Whisper sometimes glues the words together)
# Mishearings that the letter comparison would reject (different first letter or too different).
ALIASES: dict[str, set[str]] = {
    "alter": {"ultra", "otter", "alder", "altar", "alta", "alto", "altair", "author", "other", "after", "outer", "older"},
    "ego": {"eagle", "igo", "echo", "ergo", "ago", "iago", "igloo", "eco"},
    "hey": {"hay", "hei", "a", "eh", "hee"},
}
# Words that may come before the phrase ("um, hey Alter Ego"), or start it ("hey Alter Ego" vs "Alter Ego").
FILLERS = {"hey", "hi", "ok", "okay", "yo", "oh", "um", "uh", "so", "hello"}
MAX_LEAD_WORDS = 2


def words_of(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _word_match(heard: str, wanted: str) -> bool:
    if heard == wanted or heard in ALIASES.get(wanted, ()):
        return True
    # Otherwise the first letter must agree: "later" is not "alter", however similar the letters are.
    return heard[0] == wanted[0] and difflib.SequenceMatcher(None, heard, wanted).ratio() >= WORD_RATIO


def _phrase_match(heard: list[str], wanted: list[str]) -> bool:
    if len(heard) == len(wanted):
        return all(_word_match(h, w) for h, w in zip(heard, wanted))
    # A different number of words: only accept when they are the same letters glued differently.
    joined_heard, joined_wanted = "".join(heard), "".join(wanted)
    return joined_heard[0] == joined_wanted[0] and difflib.SequenceMatcher(None, joined_heard, joined_wanted).ratio() >= JOINED_RATIO


def match_wake_phrase(text: str, phrase: str = DEFAULT_PHRASE) -> str | None:
    """Return the words after the wake phrase ("" if nothing follows), or None if the phrase was not said."""
    words = words_of(text)
    phrase_words = words_of(phrase)
    if not words or not phrase_words:
        return None

    targets = [phrase_words]
    if len(phrase_words) > 1 and phrase_words[0] in FILLERS:
        targets.append(phrase_words[1:])  # "Alter Ego" on its own counts too.

    for target in targets:  # The full phrase is tried first, so its "hey" is not left in the command.
        for start in range(0, min(MAX_LEAD_WORDS + 1, len(words))):
            if start > 0 and words[start - 1] not in FILLERS:
                break  # Only fillers may precede the phrase.
            for length in range(max(1, len(target) - 1), len(target) + 2):
                end = start + length
                if end > len(words):
                    continue
                if _phrase_match(words[start:end], target):
                    return " ".join(words[end:])
    return None
