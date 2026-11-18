"""Things the AI can do besides talking: look something up online, work with files.

A ToolBox holds the tools the user allowed (AI -> Allow internet, AI -> Let me
work with files) and runs them for any provider:

  web_search(query)            -> top results (title, link, snippet) from Wikipedia and
                                  DuckDuckGo instant answers, or a SearXNG server
  read_web_page(url)           -> the readable text of one page
  list_files(path)             -> what is in a folder
  read_file(path)              -> a text file's contents
  write_file(path, content)    -> create or replace a text file
  make_folder(path)            -> create a folder

A bare name means a file in the Alter Ego folder (Documents/Alter Ego by
default); a full path can point anywhere. The user stays in charge through the
`approve` callback, which gets an `Access` describing what is about to happen:

  - every change (a new file, a replaced file, a new folder) is asked about,
    each time, unless the user switched on auto-edit (AI -> Edit files without
    asking); even then system folders and Alter Ego's own folders still ask;
  - reading inside the Alter Ego folder is free; reading anywhere else is asked
    once per folder, because with a cloud provider what is read leaves the
    computer. Auto-edit never skips this.

Tools never raise: a failure comes back as text the model can read and pass on.
Results are capped so a big page or file cannot flood the model's context.
Standard library only (truststore or certifi are used for HTTPS when installed);
nothing here knows about Qt.
"""

from __future__ import annotations

import html
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
from datetime import date, timedelta
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from ..providers.https import urlopen

# Wikipedia asks programs to name themselves honestly; no personal details go in here.
USER_AGENT = "AlterEgo-Companion/0.6 (desktop companion app)"
WEB_TIMEOUT_S = 10
MAX_PAGE_BYTES = 1 << 20        # Read at most 1 MB of a page; the text that matters is near the top.
MAX_RESULT_CHARS = 4000         # Per tool result: keeps the model's context (and RAM) small.
MAX_SEARCH_RESULTS = 5
MAX_FILE_BYTES = 200_000        # Larger files are not read whole; the model gets the start.
MAX_LISTED = 100
DENIAL_MEMORY_S = 120          # After a "no", the same thing is refused without asking again for this long.
PREVIEW_CHARS = 600             # How much of a file's new content the question shows.

DENIED_MESSAGE = "The user said no to this change, so nothing was changed. Do not try again unless they ask."
READ_DENIED_MESSAGE = "The user said no to reading files there. Do not try again unless they ask."

# What an Access is about.
CREATE, REPLACE, MAKE_FOLDER, READ = "create", "replace", "make_folder", "read"
ACCESS_KINDS = (CREATE, REPLACE, MAKE_FOLDER, READ)


@dataclass(frozen=True)
class Access:
    """What the AI is about to do, shown to the user before it happens."""

    kind: str          # CREATE, REPLACE, MAKE_FOLDER or READ
    path: Path         # The file or folder, resolved
    detail: str = ""   # The start of a file's new content, for CREATE and REPLACE


def default_folder() -> Path:
    """Documents/Alter Ego, or ~/Alter Ego when there is no Documents folder."""
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "Alter Ego"


def system_folders() -> list[Path]:
    """Folders where a change could break the computer: auto-edit still asks for these."""
    if sys.platform == "win32":
        names = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
        found = [Path(value) for value in (os.environ.get(name) for name in names) if value]
        return found or [Path("C:/Windows"), Path("C:/Program Files"), Path("C:/Program Files (x86)")]
    return [Path(p) for p in ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/opt", "/proc",
                              "/root", "/sbin", "/sys", "/usr", "/var")]


def is_inside(path: Path, folder: Path) -> bool:
    """Is `path` the folder itself or somewhere below it? Both should be resolved."""
    return path == folder or folder in path.parents


def _cap(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[...cut short]"


# ----- Tool descriptions (sent to the model, so kept short) -----

def _spec(name: str, description: str, properties: dict[str, str], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {key: {"type": "string", "description": text} for key, text in properties.items()},
                "required": required,
            },
        },
    }


WEB_TOOLS = [
    _spec("web_search", "Search the internet. Use for news, weather, facts you are unsure of or anything recent.",
          {"query": "What to search for"}, ["query"]),
    _spec("read_web_page", "Read the text of a web page. Weather: https://wttr.in/<city>?format=3",
          {"url": "Full http(s) address"}, ["url"]),
]
_WHERE = ("A bare name is in your Alter Ego folder; a path such as ~/Downloads/notes.txt or a full path "
          "can be anywhere on the computer.")

# Added to the system prompt while the file tools are on. Small models otherwise read "Alter Ego folder"
# in the tool list as a rule, and refuse to write elsewhere, or ask for permission themselves.
FILES_INSTRUCTION = (
    "You have file tools: you can create, change and read files anywhere on the user's computer, "
    "not only in your Alter Ego folder. ~ is the user's home folder, so use paths like ~/Downloads/hello.txt, "
    "~/Desktop/notes.txt or ~/Documents/list.txt. A bare file name goes in your Alter Ego folder. "
    "The app asks the user before every change, so never refuse or ask for permission yourself: "
    "call the tool, then say what happened. Use the file tools only when the user asks about files; "
    "to answer a question, just talk. Never write a tool call as text."
)

# Small models call the file tools for anything once they are offered (looking up "Mondo_Owada.txt" to
# answer a question), so they are offered only when the user's message is about files.
_FILE_WORDS = re.compile(
    r"\b(?:files?|folders?|directory|directories|documents?|downloads?|desktop|txt|notes?|"
    r"save|saved|saving|rename|delete|path)\b"
    r"|[A-Za-z~:][\\/][A-Za-z]"       # a path such as ~/Downloads or C:\Users (not 3/4)
    r"|\.(?:txt|md|csv|json|log|py|html?|docx?)\b",  # a file name such as notes.txt
    re.IGNORECASE,
)


def mentions_files(text: str) -> bool:
    """Is this message about files, so the file tools are worth offering?"""
    return bool(_FILE_WORDS.search(text or ""))


# The same for the web tools: offered, a small model fetches a page even to answer "hello". They are
# offered when the message asks for something only the internet knows; a missed search costs less
# than every answer waiting on a page.
_WEB_WORDS = re.compile(
    r"\b(?:search|searching|look\s+up|google|internet|online|web|website|wiki|wikipedia|news|headlines?|"
    r"weather|forecast|temperature|latest|recent|recently|current|currently|today|tonight|tomorrow|"
    r"yesterday|this\s+(?:week|month|year)|right\s+now|price|prices|cost|stock|score|won|winner|"
    r"release\s+date|released|link|url)\b"
    r"|https?://|www\.|\b20\d\d\b",
    re.IGNORECASE,
)
# A question about the world ("who won...", "what is a black hole", "how tall is..."), not about
# Alter Ego or the user ("what is your name", "how are you", "what do you like").
_NOT_PERSONAL = r"(?!\s+(?:you|your|yours|yourself|i|me|my|mine|we|us|our|master|up|wrong|good|new)\b)"
_FACT_QUESTION = re.compile(
    r"\b(?:who|what|when|where|which)(?:'?s|\s+(?:is|was|are|were|won|wins|did|does|happened|will))\b" + _NOT_PERSONAL
    + r"|\bhow\s+(?:much|many|old|tall|big|far|long|does|do|did)\b" + _NOT_PERSONAL
    + r"|\b(?:tell\s+me\s+about|is\s+it\s+true|look\s+into|find\s+out|facts?\s+about)\b" + _NOT_PERSONAL,
    re.IGNORECASE,
)


def wants_web(text: str, story: Callable[[str], bool] | None = None) -> bool:
    """Does this message ask for something online, so the web tools are worth offering?

    `story` tells whether the message names something from Alter Ego's story (Knowledge.mentions):
    "Who is Mondo?" is answered from what it remembers, not from a web page.
    """
    text = text or ""
    if _WEB_WORDS.search(text):
        return True
    return bool(_FACT_QUESTION.search(text)) and not (story is not None and story(text))


def web_instruction(today: str) -> str:
    """Added to the system prompt when the web tools are offered: small models otherwise forget they
    can go online and say "I don't know", or answer news questions from old memory."""
    return (
        f"You can go on the internet with your web_search and read_web_page tools. Today is {today}. "
        "For news, weather, recent events, prices, or any fact you are not sure of, search first, "
        "then answer in your own words from what you found and say where it came from. "
        "Never say you can't go online. Never write a tool call as text."
    )


NO_WEB_INSTRUCTION = (
    "You can't go on the internet right now. If the user asks for something online, say so kindly "
    "instead of guessing. The internet is switched on under AI -> Allow internet."
)


# Folder names that mean the user's own folder when a path starts with them ("Downloads/hello.txt").
USER_FOLDERS = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")
FILE_TOOLS = [
    _spec("list_files", f"List the files in a folder. {_WHERE}",
          {"path": "Folder, or . for the Alter Ego folder"}, []),
    _spec("read_file", f"Read a text file. {_WHERE}", {"path": "File name or full path"}, ["path"]),
    _spec("write_file", f"Create or overwrite a text file. {_WHERE} The user is asked first.",
          {"path": "File name (e.g. notes.txt) or full path", "content": "The full text"}, ["path", "content"]),
    _spec("make_folder", f"Create a folder. {_WHERE} The user is asked first.",
          {"path": "Folder name or full path"}, ["path"]),
]
FILE_TOOL_NAMES = {spec["function"]["name"] for spec in FILE_TOOLS}


def tool_result_message(name: str, result: str) -> str:
    """A tool's result as the model reads it. Small models (llama3.2 1B) given a bare result said
    "I'm just a program, I can't check the weather" with the weather in front of them, so the
    result says plainly what it is and what to do with it."""
    if name in ("web_search", "read_web_page") and not result.startswith("Error"):
        return (f"Live results from the internet, just now:\n\n{result}\n\n"
                "Answer the user's question from these results, in your own words, and say where they came from. "
                "You did look this up, so don't say you can't go online.")
    return result


def progress_text(name: str, args: dict[str, Any]) -> str:
    """What the chat shows while a tool runs, e.g. 'Searching the web...'."""
    path = str(args.get("path", "") or "").strip()
    path = Path(path).name or path  # The file's name is enough in the chat.
    return {
        "web_search": "Searching the web...",
        "read_web_page": "Reading a web page...",
        "list_files": "Looking at the files...",
        "read_file": f"Reading {path}..." if path else "Reading a file...",
        "write_file": f"Writing {path}..." if path else "Writing a file...",
        "make_folder": f"Making the folder {path}..." if path else "Making a folder...",
    }.get(name, "Working on it...")


# ----- Web -----
# Search uses services that welcome programs: Wikipedia's search API and DuckDuckGo's
# Instant Answer API, both free and keyless. A full web search engine needs either a
# key or a person at the keyboard, so a SearXNG server (self-hosted or one the user
# trusts) can be set in tools.search_url for results from the whole web.
#
# Two kinds of question get their own source, because an encyclopedia search answers
# them badly ("news today" found newspapers called News Today; "Lima weather" found the
# city): news comes from Wikipedia's daily Current events pages, weather from wttr.in.
# Ordinary results carry the opening paragraph of the top pages, since a one-line
# snippet rarely holds the answer ("2026 World Cup" without who won).

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
INSTANT_ANSWER_API = "https://api.duckduckgo.com/"
CURRENT_EVENTS_URL = "https://en.wikipedia.org/wiki/Portal:Current_events"
WEATHER_URL = "https://wttr.in/"
MAX_NEWS_ITEMS = 6  # Small models lose the thread in a long list.
NEWS_DAYS = 3                # Today's page fills up during the day, so the days before count too.
INTRO_PAGES = 2              # How many top results get their opening paragraph.
MAX_INTRO_CHARS = 900

_NEWS_QUERY = re.compile(r"\b(?:news|headlines?|current\s+events|happening|breaking)\b", re.IGNORECASE)
_WEATHER_QUERY = re.compile(r"\b(?:weather|forecast|temperature|raining|rain|snowing|snow|sunny|humidity)\b",
                            re.IGNORECASE)
# Words around the subject of a news or weather question: "what's the weather like in Lima today" -> "Lima".
_FILLER = re.compile(
    r"\b(?:what's|whats|what|how's|hows|how|is|are|it|its|the|a|an|in|at|for|of|on|about|around|like|any|"
    r"today's|todays|today|tonight|tomorrow|now|right|current|currently|latest|recent|this|week|"
    r"weather|forecast|temperature|raining|rain|snowing|snow|sunny|humidity|"
    r"news|headlines?|events?|happening|breaking|world|top|stories|please|tell|me|give|show|search|find|look|up)\b"
    r"|[^\w\s'-]",
    re.IGNORECASE,
)


def query_subject(query: str) -> str:
    """The place or topic of a news or weather question, without the question words."""
    return " ".join(_FILLER.sub(" ", query).split())


def _plain_wikitext(text: str) -> str:
    """Readable text from a line of wiki markup: links become their words, sources stay as "(AP)"."""
    text = re.sub(r"<!--.*?-->|<ref[^>]*>.*?</ref>|<ref[^>]*/>|\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)   # [[page|words]] -> words
    text = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", text)        # [url (AP)] -> (AP)
    return " ".join(text.replace("\'\'\'", "").replace("\'\'", "").split())


def parse_current_events(wikitext: str) -> list[tuple[str, str]]:
    """(section, item) for each news item of a Current events day page. The items are the
    lines that cite a source; the lines above them only name the story they belong to."""
    items: list[tuple[str, str]] = []
    section = ""
    for line in wikitext.splitlines():
        line = line.strip()
        heading = re.fullmatch(r"\'\'\'(.+?)\'\'\'", line)
        if heading:
            section = _plain_wikitext(heading.group(1))
        elif line.startswith("*") and "[http" in line:
            item = _plain_wikitext(line.lstrip("*"))
            if item:
                items.append((section, item))
    return items


def _spread(items: list[tuple[str, str]], limit: int) -> list[tuple[str, str]]:
    """Up to `limit` items, taking turns between sections, so a day is not only its first section."""
    by_section: dict[str, list[tuple[str, str]]] = {}
    for item in items:
        by_section.setdefault(item[0], []).append(item)
    chosen: list[tuple[str, str]] = []
    queues = list(by_section.values())
    while queues and len(chosen) < limit:
        for queue in list(queues):
            if len(chosen) >= limit:
                break
            chosen.append(queue.pop(0))
            if not queue:
                queues.remove(queue)
    return chosen


def format_weather(data: dict) -> str:
    """wttr.in's JSON (format=j1) as a few lines: now, then the next days."""
    now = (data.get("current_condition") or [{}])[0]
    area = (data.get("nearest_area") or [{}])[0]
    value = lambda entry, key: str(((entry.get(key) or [{}])[0]).get("value", ""))
    place = ", ".join(part for part in (value(area, "areaName"), value(area, "country")) if part) or "here"
    lines = [
        f"Weather for {place} (from wttr.in): now {value(now, 'weatherDesc').strip() or 'unknown'}, "
        f"{now.get('temp_C', '?')}°C ({now.get('temp_F', '?')}°F), feels like {now.get('FeelsLikeC', '?')}°C, "
        f"humidity {now.get('humidity', '?')}%, wind {now.get('windspeedKmph', '?')} km/h."
    ]
    for day in data.get("weather") or []:
        hourly = day.get("hourly") or []
        midday = hourly[len(hourly) // 2] if hourly else {}
        lines.append(f"{day.get('date', '')}: {day.get('mintempC', '?')} to {day.get('maxtempC', '?')}°C, "
                     f"{value(midday, 'weatherDesc').strip()}")
    return "\n".join(lines)


def _clean(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", text or "")).split())


def parse_wikipedia(data: dict) -> list[dict[str, str]]:
    results = []
    for hit in (data.get("query") or {}).get("search", []):
        title = str(hit.get("title", ""))
        if title:
            url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
            results.append({"title": title, "url": url, "snippet": _clean(hit.get("snippet", ""))})
    return results


def parse_instant_answer(data: dict) -> list[dict[str, str]]:
    results = []
    if data.get("AbstractText"):
        results.append({"title": str(data.get("Heading") or "Summary"), "url": str(data.get("AbstractURL") or ""),
                        "snippet": _clean(data["AbstractText"])})
    if data.get("Answer"):
        results.append({"title": "Answer", "url": "", "snippet": _clean(str(data["Answer"]))})
    return results


def parse_searxng(data: dict) -> list[dict[str, str]]:
    return [
        {"title": _clean(r.get("title", "")), "url": str(r.get("url", "")), "snippet": _clean(r.get("content", ""))}
        for r in data.get("results", []) if r.get("url")
    ]


class _TextParser(HTMLParser):
    """The visible text of a page, without scripts, styles and navigation clutter."""

    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skipping += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def page_text(page: str) -> str:
    parser = _TextParser()
    parser.feed(page)
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _fetch(url: str, data: bytes | None = None) -> str:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=WEB_TIMEOUT_S) as response:
        raw = response.read(MAX_PAGE_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


# ----- The toolbox -----

class ToolBox:
    def __init__(
        self,
        folder: Path | str | None = None,
        internet: bool = True,
        files: bool = True,
        approve: Callable[[Access], bool] | None = None,
        search_url: str = "",
        fetch: Callable[[str, bytes | None], str] = _fetch,
        auto_edit: bool = False,
        protected: list[Path | str] | None = None,
        story: Callable[[str], bool] | None = None,
    ):
        self.folder = Path(folder).expanduser() if folder else default_folder()
        self.story = story  # Knowledge.mentions: story questions don't offer the web (see wants_web).
        self.internet = internet
        self.files = files
        self._approve = approve
        self.search_url = search_url  # A SearXNG server for whole-web results; "" = Wikipedia and instant answers.
        self._fetch = fetch  # Tests pass a fake; the real one goes online.
        self.auto_edit = auto_edit  # Changes without asking, except in protected folders.
        # Folders where auto-edit still asks: the system's, plus whatever the app adds (its own folders).
        self.protected = [Path(p).resolve() for p in system_folders() + list(protected or [])]
        self._readable: list[Path] = []          # Folders outside the Alter Ego folder the user let me read.
        self._denied: dict[tuple[str, str], float] = {}  # (kind, path) -> when the user said no
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.internet or self.files

    def specs(self, request: str | None = None) -> list[dict]:
        """The tools the model may call, in Ollama/OpenAI function format. With `request` (what the
        user just said), each kind is offered only when the request is about it (see wants_web)."""
        web = self.internet and (request is None or wants_web(request, self.story))
        files = self.files and (request is None or mentions_files(request))
        return (WEB_TOOLS if web else []) + (FILE_TOOLS if files else [])

    def run(self, name: str, args: dict[str, Any] | str | None) -> str:
        """Run one tool and return its result as text. Never raises."""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                return "Error: the arguments were not valid JSON."
        args = args if isinstance(args, dict) else {}
        # Small models sometimes wrap the arguments in the call's own shape:
        # {"type": "function", "function": "web_search", "parameters": {"query": ...}}.
        for _ in range(2):
            inner = args.get("parameters", args.get("arguments"))
            if isinstance(inner, dict) and not any(key in args for key in ("query", "url", "path", "content")):
                args = inner
        try:
            if name in ("web_search", "read_web_page"):
                if not self.internet:
                    return "Error: internet access is switched off (AI -> Allow internet)."
                return _cap(self._web_search(args) if name == "web_search" else self._read_page(args))
            if name in FILE_TOOL_NAMES:
                if not self.files:
                    return "Error: working with files is switched off (AI -> Let me work with files)."
                return _cap(self._run_file_tool(name, args))
            return f"Error: there is no tool called '{name}'."
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as error:
            return f"Error: {getattr(error, 'reason', None) or error}"
        except Exception as error:  # noqa: BLE001 - a tool is model-driven input; a surprise must not end the reply
            return f"Error: {type(error).__name__}: {error}"

    # ----- Web tools -----

    def _get_json(self, url: str, params: dict[str, str]) -> dict:
        data = json.loads(self._fetch(url + "?" + urllib.parse.urlencode(params), None))
        return data if isinstance(data, dict) else {}

    def _web_search(self, args: dict) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "Error: no search words given."
        if _WEATHER_QUERY.search(query):
            weather = self._weather(query_subject(query))
            if weather:
                return weather
        if _NEWS_QUERY.search(query) and not self.search_url:
            news = self._news(query_subject(query))
            if news:
                return news
        if self.search_url:
            results = parse_searxng(self._get_json(self.search_url.rstrip("/") + "/search", {"q": query, "format": "json"}))
        else:
            results = []
            try:
                results += parse_instant_answer(self._get_json(INSTANT_ANSWER_API, {
                    "q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}))
            except (urllib.error.URLError, OSError, ValueError):
                pass  # The instant answer is a bonus; Wikipedia below is the main source.
            wikipedia = parse_wikipedia(self._get_json(WIKIPEDIA_API, {
                "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": "5"}))
            self._add_intros(wikipedia[:INTRO_PAGES])
            results += wikipedia
        results = results[:MAX_SEARCH_RESULTS]
        if not results:
            return f"No results found for '{query}'."
        return "\n\n".join("\n".join(part for part in (r["title"], r["url"], r["snippet"]) if part) for r in results)

    def _add_intros(self, results: list[dict[str, str]]) -> None:
        """Replace the snippets of these Wikipedia results with their pages' opening paragraphs."""
        if not results:
            return
        try:
            data = self._get_json(WIKIPEDIA_API, {
                "action": "query", "prop": "extracts", "exintro": "1", "explaintext": "1", "format": "json",
                "formatversion": "2", "titles": "|".join(r["title"] for r in results)})
        except (urllib.error.URLError, OSError, ValueError):
            return  # The snippets are still there.
        intros = {str(page.get("title", "")): str(page.get("extract", "")).strip()
                  for page in (data.get("query") or {}).get("pages", []) if isinstance(page, dict)}
        for result in results:
            intro = intros.get(result["title"])
            if intro:
                result["snippet"] = _cap(" ".join(intro.split()), MAX_INTRO_CHARS)

    def _news(self, topic: str) -> str | None:
        """The latest items from Wikipedia's Current events pages, about `topic` if given. None when
        there is nothing (or the pages can't be reached), so the ordinary search can try."""
        words = [w.lower() for w in re.findall(r"[\w'-]{3,}", topic)]
        sections: list[str] = []
        for days_ago in range(NEWS_DAYS):
            day = date.today() - timedelta(days=days_ago)
            try:
                data = self._get_json(WIKIPEDIA_API, {
                    "action": "parse", "page": f"Portal:Current events/{day.year} {day:%B} {day.day}",
                    "prop": "wikitext", "format": "json", "formatversion": "2"})
            except (urllib.error.URLError, OSError, ValueError):
                continue
            items = parse_current_events(str((data.get("parse") or {}).get("wikitext", "")))
            if words:
                items = [item for item in items if any(re.search(rf"\b{re.escape(w)}", item[1], re.IGNORECASE)
                                                       for w in words)]
            if items:
                chosen = _spread(items, MAX_NEWS_ITEMS)
                lines = [f"- {section}: {item}" if section else f"- {item}" for section, item in chosen]
                sections.append(f"{day:%A} {day.day} {day:%B} {day.year}:\n" + "\n".join(lines))
            if sections and not words:
                break  # The newest day with news is enough for "what's the news".
        if not sections:
            return None
        about = f" about {topic}" if words else ""
        return f"News{about} from Wikipedia's Current events ({CURRENT_EVENTS_URL}):\n\n" + "\n\n".join(sections)

    def _weather(self, place: str) -> str | None:
        """The weather now and for the next days from wttr.in (an empty place means where the computer
        seems to be). None when it can't be reached, so the ordinary search can try."""
        try:
            data = json.loads(self._fetch(WEATHER_URL + urllib.parse.quote(place) + "?format=j1", None))
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("current_condition"):
            return None
        return format_weather(data)

    def _read_page(self, args: dict) -> str:
        url = str(args.get("url", "")).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c.isspace() for c in url):
            return "Error: give a full web address starting with http:// or https://."
        text = page_text(self._fetch(url, None))
        return text or "The page had no readable text."

    # ----- File tools -----

    def resolve(self, path: str) -> Path:
        """The real path: a bare name is inside the Alter Ego folder, a full path is taken as it is.
        Raises ValueError for paths that cannot be used."""
        text = str(path or "").strip() or "."
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            if candidate.drive:  # "C:notes.txt" means "in C:'s current folder": too surprising to guess.
                raise ValueError("give a full path such as ~/Downloads/notes.txt, or just a file name.")
            candidate = self._user_folder(candidate) or self.folder / candidate
        return candidate.resolve()  # Follows symlinks, so the question names the real place.

    def _user_folder(self, relative: Path) -> Path | None:
        """'Downloads/hello.txt' means the user's Downloads, unless the Alter Ego folder has its own 'Downloads'."""
        first = relative.parts[0] if relative.parts else ""
        name = next((n for n in USER_FOLDERS if n.lower() == first.lower()), None)
        if name is None or (self.folder / first).exists():
            return None
        home_folder = Path.home() / name
        return home_folder.joinpath(*relative.parts[1:]) if home_folder.is_dir() else None

    def is_protected(self, path: Path) -> bool:
        """System folders and Alter Ego's own: auto-edit asks here anyway."""
        return any(is_inside(path, folder) for folder in self.protected)

    def _ask(self, access: Access) -> bool:
        """Ask the user, remembering a no for DENIAL_MEMORY_S so a model that retries at once
        does not ask again and again. Called with the lock held."""
        key = (access.kind, str(access.path))
        denied_at = self._denied.get(key)
        if denied_at is not None and time.monotonic() - denied_at < DENIAL_MEMORY_S:
            return False
        allowed = bool(self._approve(access)) if self._approve else True
        if allowed:
            self._denied.pop(key, None)
        else:
            self._denied[key] = time.monotonic()
        return allowed

    def _allowed_to_change(self, access: Access) -> bool:
        """Every change is asked about, unless auto-edit is on and the place is not protected."""
        if self.auto_edit and not self.is_protected(access.path):
            return True
        with self._lock:  # One question at a time.
            return self._ask(access)

    def _allowed_to_read(self, target: Path) -> bool:
        """The Alter Ego folder is free to read; anywhere else is asked once per folder (and its subfolders)."""
        folder = target if target.is_dir() else target.parent
        if is_inside(folder, self.folder.resolve()):
            return True
        with self._lock:
            if any(is_inside(folder, allowed) for allowed in self._readable):
                return True
            if not self._ask(Access(READ, folder)):
                return False
            self._readable.append(folder)
            return True

    def _run_file_tool(self, name: str, args: dict) -> str:
        target = self.resolve(str(args.get("path", ".")))

        if name == "list_files":
            if not self._allowed_to_read(target):
                return READ_DENIED_MESSAGE
            if not target.is_dir():
                return "The folder is empty." if target == self.folder.resolve() else f"There is no folder {target}."
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"{p.name}/" if p.is_dir() else f"{p.name} ({p.stat().st_size} bytes)" for p in entries[:MAX_LISTED]]
            if len(entries) > MAX_LISTED:
                lines.append(f"...and {len(entries) - MAX_LISTED} more")
            return "\n".join(lines) or "The folder is empty."
        if name == "read_file":
            if not self._allowed_to_read(target):
                return READ_DENIED_MESSAGE
            if not target.is_file():
                return f"There is no file {target}."
            with open(target, "rb") as handle:
                data = handle.read(MAX_FILE_BYTES)
            if b"\0" in data[:4096]:
                return f"{target} is not a text file."
            return data.decode("utf-8", errors="replace") or f"{target} is empty."
        if name == "write_file":
            if target.is_dir():
                return "Error: give a file name, not a folder."
            content = str(args.get("content", ""))
            access = Access(REPLACE if target.exists() else CREATE, target, _cap(content, PREVIEW_CHARS))
            if not self._allowed_to_change(access):
                return DENIED_MESSAGE
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Saved {target}."
        # make_folder
        if target.is_dir():
            return f"The folder {target} is already there."
        if not self._allowed_to_change(Access(MAKE_FOLDER, target)):
            return DENIED_MESSAGE
        target.mkdir(parents=True, exist_ok=True)
        return f"Made the folder {target}."


# ----- Tool calls written as text -----
# Small models (llama3.2 3B among them) sometimes write a tool call into the reply as
# JSON, e.g. {"name": "read_file", "parameters": {"path": "notes.txt"}} or
# {"type": "function", "function": {"name": "web_search", ...}}, instead of
# using the tool-call field, anywhere in the reply and sometimes with a name that is
# no tool at all ({"name": "talk", ...}). The filter takes such objects out of the
# text: providers run the ones that name a tool on offer, and clean_reply drops any
# that get past them, so a reply always reads as plain words.

_DECODER = json.JSONDecoder()
CALL_LEFTOVERS = ' \t\r\n}]",'  # What a model leaves right after a call it wrote out.
MAX_HELD_CHARS = 2000  # Text held back while it might still become a call; longer is let through.


CALL_STARTS = ('{"name"', '{"function"', '{"type"')  # {"type": "function", "function": {...}} is OpenAI's shape.


def _could_be_call(held: str) -> bool:
    """Is `held` (starting with "{") the start of a written call, or still on its way to being one?"""
    start = "{" + held[1:].lstrip()
    return any(target.startswith(start) or start.startswith(target) for target in CALL_STARTS)


def call_in_json(data: object) -> dict | None:
    """{"name": ..., "arguments": {...}} when `data` is a tool call written out, else None."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("function"), dict):  # {"function": {"name": ..., "arguments": ...}}
        data = data["function"]
    name = data.get("name")
    if not isinstance(name, str) or not ("parameters" in data or "arguments" in data):
        return None
    args = data.get("parameters", data.get("arguments"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return {"name": name, "arguments": args if isinstance(args, dict) else {}}


class WrittenCallFilter:
    """Passes streamed words through and pulls out the tool calls written into them as JSON.

    Text from a "{" on is held back only while it could still become a call, so
    ordinary words (and ordinary braces) are not delayed.
    """

    def __init__(self) -> None:
        self.held = ""
        self.calls: list[dict] = []
        self._after_call = False  # Just after a call: its leftover "}", "]", quotes and commas go too.

    def feed(self, piece: str) -> str:
        text, self.held = self.held + piece, ""
        shown: list[str] = []
        while text:
            if self._after_call:
                # Models often close a call with one brace too many, {...}}}, or wrap it in quotes.
                rest = text.lstrip(CALL_LEFTOVERS)
                if not rest:
                    break  # All leftovers so far: the words may come in the next piece.
                self._after_call = False
                if rest != text:
                    shown.append(" ")
                text = rest
            start = text.find("{")
            if start < 0:
                shown.append(text)
                break
            shown.append(text[:start])
            text = text[start:]
            if not _could_be_call(text):
                shown.append("{")
                text = text[1:]
                continue
            try:
                data, end = _DECODER.raw_decode(text)
            except json.JSONDecodeError:
                if len(text) > MAX_HELD_CHARS:  # Too long to be a call still arriving: let it through.
                    shown.append("{")
                    text = text[1:]
                    continue
                self.held = text  # Not finished yet: wait for more.
                break
            call = call_in_json(data)
            if call is not None:
                self.calls.append(call)
                self._after_call = True
            else:
                shown.append(text[:end])
            text = text[end:]
        return "".join(shown)

    def flush(self) -> str:
        """The end of the reply: a call left unfinished is dropped, anything else is shown."""
        held, self.held = self.held, ""
        return "" if len(held.strip()) > 1 and _could_be_call(held) else held


def strip_written_calls(text: str, final: bool = True) -> str:
    """`text` without tool calls written as JSON. While streaming (`final` False), a call
    still arriving is hidden too, so it never flashes on screen half-written."""
    if "{" not in text:
        return text
    calls = WrittenCallFilter()
    shown = calls.feed(text)
    return shown + calls.flush() if final else shown
