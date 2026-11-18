"""Cutting a reply into sentences as it streams in, so speech starts before the reply ends.

Replies arrive piece by piece. Each time more text is known, take_sentences()
hands back the sentences that are complete and how much text they used; the
caller keeps the rest for next time. When the reply is finished (`final`),
whatever is left is a sentence too.
"""

from __future__ import annotations

import re

# A sentence ends with . ! ? or … (maybe several, maybe followed by a closing
# quote or bracket), then whitespace. A newline always ends one too.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)|\n+")
# Very short fragments ("Oh!") are spoken together with what follows: they
# sound choppy on their own and cost a model run each.
MIN_CHARS = 12
# Long sentences are fine for the model, but the first one should start playing soon.
MAX_CHARS = 400
# The first piece of a reply is what everyone waits for (the chat types along with the voice), so a
# long first sentence is spoken in two parts, cut at a comma: on a CPU about 1 s to the first sound
# instead of 3. Neither part is left shorter than FIRST_MIN_CHARS, which would sound choppy.
FIRST_SPLIT_CHARS = 60
FIRST_MIN_CHARS = 25
# A stammered start of a word: one to three letters and a hyphen, followed by the same letters.
# Real prefixes ("re-read", "pre-prepared") are not stammers and are left alone.
_STAMMER = re.compile(r"\b(?!(?:re|co|de|un|ex|bi|pre|pro|sub|non|mid|tri|anti)-)([A-Za-z]{1,3})-(?=\1)", re.IGNORECASE)


def take_sentences(text: str, final: bool, first: bool = False) -> tuple[list[str], int]:
    """Split the complete sentences off the front of `text`.

    Returns (sentences, consumed): `consumed` is the number of characters of
    `text` used, so the caller can pass text[consumed:] (plus new text) next
    time. With `final`, all of `text` is consumed. `first` means `text` starts
    the reply: a long first sentence is then cut in two at a comma.
    """
    sentences, consumed = _take_sentences(text, final)
    if first and sentences:
        sentences[:1] = _split_first(sentences[0])
    return sentences, consumed


def _split_first(sentence: str) -> list[str]:
    if len(sentence) <= FIRST_SPLIT_CHARS:
        return [sentence]
    for match in re.finditer(r"[,;] ", sentence):
        cut = match.start() + 1
        if cut >= FIRST_MIN_CHARS and len(sentence) - cut >= FIRST_MIN_CHARS:
            return [sentence[:cut].strip(), sentence[cut:].strip()]
    return [sentence]


def _take_sentences(text: str, final: bool) -> tuple[list[str], int]:
    sentences: list[str] = []
    start = 0
    pending_start = 0  # Start of a short fragment waiting to be joined with the next sentence.

    for match in _SENTENCE_END.finditer(text):
        end = match.end()
        candidate = text[pending_start:end].strip()
        if not candidate:
            start = end
            pending_start = end
            continue
        if len(candidate) < MIN_CHARS and not _is_paragraph_break(match.group()):
            start = end  # Keep collecting; the fragment starts at pending_start.
            continue
        sentences.extend(_chunk(candidate))
        start = end
        pending_start = end

    if final:
        rest = text[pending_start:].strip()
        if rest:
            sentences.extend(_chunk(rest))
        return sentences, len(text)
    return sentences, pending_start


def _is_paragraph_break(ending: str) -> bool:
    return "\n" in ending


def _chunk(sentence: str) -> list[str]:
    """Split an over-long sentence at commas or spaces so each part stays under MAX_CHARS."""
    sentence = " ".join(sentence.split())  # Collapse newlines and runs of spaces.
    if len(sentence) <= MAX_CHARS:
        return [sentence]
    parts: list[str] = []
    while len(sentence) > MAX_CHARS:
        cut = max(sentence.rfind(", ", 0, MAX_CHARS), sentence.rfind("; ", 0, MAX_CHARS))
        if cut < MAX_CHARS // 2:
            cut = sentence.rfind(" ", 0, MAX_CHARS)
        if cut <= 0:
            cut = MAX_CHARS
        parts.append(sentence[: cut + 1].strip())
        sentence = sentence[cut + 1:].strip()
    if sentence:
        parts.append(sentence)
    return parts


def speakable(text: str) -> str:
    """Drop things that read fine but sound wrong when spoken aloud."""
    text = text.replace("▌", "")
    # "(...sorry, I lost the connection: HTTP 500 ...)" style notes: keep the words, drop the brackets.
    text = re.sub(r"\(\.\.\.", "(", text)
    text = re.sub(r"[`#*_>|]+", "", text)  # Markdown leftovers.
    # The written stammer is character ("I-I'm", "th-thank"), but read aloud it comes out as
    # "I I'm" or a spelled-out "th": speak the word once. "e-mail" and "well-known" are left
    # alone because the part after the hyphen does not repeat the part before it.
    text = _STAMMER.sub("", text)
    return " ".join(text.split()) if "\n" not in text else text
