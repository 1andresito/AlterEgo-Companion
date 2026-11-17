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

Files are only ever touched inside one folder (Documents/Alter Ego by default):
every path is resolved against it and anything that points outside is refused.
Before the first change in a run Alter Ego asks the user ("I'm going to be
editing <folder>. Is this okay?") through the `approve` callback; the answer
holds until the app quits.

Tools never raise: a failure comes back as text the model can read and pass on.
Results are capped so a big page or file cannot flood the model's context.
Standard library only (truststore or certifi are used for HTTPS when installed);
nothing here knows about Qt.
"""

from __future__ import annotations

import html
import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

# Wikipedia asks programs to name themselves honestly; no personal details go in here.
USER_AGENT = "AlterEgo-Companion/0.6 (desktop companion app)"
WEB_TIMEOUT_S = 10
MAX_PAGE_BYTES = 1 << 20        # Read at most 1 MB of a page; the text that matters is near the top.
MAX_RESULT_CHARS = 4000         # Per tool result: keeps the model's context (and RAM) small.
MAX_SEARCH_RESULTS = 5
MAX_FILE_BYTES = 200_000        # Larger files are not read whole; the model gets the start.
MAX_LISTED = 100
DENIAL_MEMORY_S = 120          # After a "no", writes are refused without asking again for this long.

DENIED_MESSAGE = "The user said no to editing files, so nothing was changed. Do not try again unless they ask."


def default_folder() -> Path:
    """Documents/Alter Ego, or ~/Alter Ego when there is no Documents folder."""
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "Alter Ego"


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
    _spec("web_search", "Search the internet. Use for facts you are unsure of or anything recent.",
          {"query": "What to search for"}, ["query"]),
    _spec("read_web_page", "Read the text of a web page. Weather: https://wttr.in/<city>?format=3",
          {"url": "Full http(s) address"}, ["url"]),
]
FILE_TOOLS = [
    _spec("list_files", "List files in the user's Alter Ego folder.", {"path": "Subfolder, or . for the top"}, []),
    _spec("read_file", "Read a text file in the user's Alter Ego folder.", {"path": "File name"}, ["path"]),
    _spec("write_file", "Create or overwrite a text file in the user's Alter Ego folder.",
          {"path": "File name, e.g. notes.txt", "content": "The full text"}, ["path", "content"]),
    _spec("make_folder", "Create a folder in the user's Alter Ego folder.", {"path": "Folder name"}, ["path"]),
]
FILE_TOOL_NAMES = {spec["function"]["name"] for spec in FILE_TOOLS}
WRITING_TOOLS = {"write_file", "make_folder"}


def progress_text(name: str, args: dict[str, Any]) -> str:
    """What the chat shows while a tool runs, e.g. 'Searching the web...'."""
    path = str(args.get("path", "") or "")
    return {
        "web_search": "Searching the web...",
        "read_web_page": "Reading a web page...",
        "list_files": "Looking in my folder...",
        "read_file": f"Reading {path}..." if path else "Reading a file...",
        "write_file": f"Writing {path}..." if path else "Writing a file...",
        "make_folder": f"Making the folder {path}..." if path else "Making a folder...",
    }.get(name, "Working on it...")


# ----- Web -----
# Search uses services that welcome programs: Wikipedia's search API and DuckDuckGo's
# Instant Answer API, both free and keyless. A full web search engine needs either a
# key or a person at the keyboard, so a SearXNG server (self-hosted or one the user
# trusts) can be set in tools.search_url for results from the whole web.

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
INSTANT_ANSWER_API = "https://api.duckduckgo.com/"


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


def _ssl_context():
    """The operating system's certificate check when truststore is installed, else certifi, else Python's own.

    Python's built-in check on Windows cannot fetch missing intermediate certificates,
    so some ordinary sites fail with CERTIFICATE_VERIFY_FAILED; the system check does not.
    """
    import ssl

    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(url: str, data: bytes | None = None) -> str:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=WEB_TIMEOUT_S, context=_ssl_context()) as response:
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
        approve: Callable[[Path], bool] | None = None,
        search_url: str = "",
        fetch: Callable[[str, bytes | None], str] = _fetch,
    ):
        self.folder = Path(folder) if folder else default_folder()
        self.internet = internet
        self.files = files
        self._approve = approve
        self.search_url = search_url  # A SearXNG server for whole-web results; "" = Wikipedia and instant answers.
        self._fetch = fetch  # Tests pass a fake; the real one goes online.
        self._approved = False
        self._denied_at: float | None = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.internet or self.files

    def specs(self) -> list[dict]:
        """The tools the model may call, in Ollama/OpenAI function format."""
        return (WEB_TOOLS if self.internet else []) + (FILE_TOOLS if self.files else [])

    def run(self, name: str, args: dict[str, Any] | str | None) -> str:
        """Run one tool and return its result as text. Never raises."""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                return "Error: the arguments were not valid JSON."
        args = args if isinstance(args, dict) else {}
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
        if self.search_url:
            results = parse_searxng(self._get_json(self.search_url.rstrip("/") + "/search", {"q": query, "format": "json"}))
        else:
            results = []
            try:
                results += parse_instant_answer(self._get_json(INSTANT_ANSWER_API, {
                    "q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}))
            except (urllib.error.URLError, OSError, ValueError):
                pass  # The instant answer is a bonus; Wikipedia below is the main source.
            results += parse_wikipedia(self._get_json(WIKIPEDIA_API, {
                "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": "5"}))
        results = results[:MAX_SEARCH_RESULTS]
        if not results:
            return f"No results found for '{query}'."
        return "\n\n".join("\n".join(part for part in (r["title"], r["url"], r["snippet"]) if part) for r in results)

    def _read_page(self, args: dict) -> str:
        url = str(args.get("url", "")).strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or any(c.isspace() for c in url):
            return "Error: give a full web address starting with http:// or https://."
        text = page_text(self._fetch(url, None))
        return text or "The page had no readable text."

    # ----- File tools -----

    def resolve(self, path: str) -> Path:
        """The real path inside the folder. Raises ValueError for anything that points outside it."""
        root = self.folder.resolve()
        candidate = Path(str(path or ".").strip() or ".")
        if candidate.is_absolute() or candidate.drive:
            raise ValueError(f"I can only use files inside {self.folder}.")
        target = (root / candidate).resolve()  # resolve() follows symlinks, so a link out is caught too.
        if target != root and root not in target.parents:
            raise ValueError(f"I can only use files inside {self.folder}.")
        return target

    def _allowed_to_write(self) -> bool:
        """Ask before the first change. A yes lasts (the approver remembers it for the run);
        a no lasts DENIAL_MEMORY_S, so a model that retries at once does not ask again and again."""
        with self._lock:  # Two writes at once must not ask twice.
            if self._approved:
                return True
            if self._denied_at is not None and time.monotonic() - self._denied_at < DENIAL_MEMORY_S:
                return False
            self._approved = bool(self._approve(self.folder)) if self._approve else True
            self._denied_at = None if self._approved else time.monotonic()
            return self._approved

    def _run_file_tool(self, name: str, args: dict) -> str:
        if name in WRITING_TOOLS and not self._allowed_to_write():
            return DENIED_MESSAGE
        if name in WRITING_TOOLS:
            self.folder.mkdir(parents=True, exist_ok=True)
        target = self.resolve(str(args.get("path", ".")))
        shown = target.relative_to(self.folder.resolve()).as_posix() if target != self.folder.resolve() else "."

        if name == "list_files":
            if not target.is_dir():
                return f"There is no folder '{shown}' yet." if shown != "." else "The folder is empty."
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            lines = [f"{p.name}/" if p.is_dir() else f"{p.name} ({p.stat().st_size} bytes)" for p in entries[:MAX_LISTED]]
            if len(entries) > MAX_LISTED:
                lines.append(f"...and {len(entries) - MAX_LISTED} more")
            return "\n".join(lines) or "The folder is empty."
        if name == "read_file":
            if not target.is_file():
                return f"There is no file '{shown}'."
            with open(target, "rb") as handle:
                data = handle.read(MAX_FILE_BYTES)
            if b"\0" in data[:4096]:
                return f"'{shown}' is not a text file."
            return data.decode("utf-8", errors="replace") or f"'{shown}' is empty."
        if name == "write_file":
            if target == self.folder.resolve() or target.is_dir():
                return "Error: give a file name, not a folder."
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(args.get("content", ""))
            target.write_text(content, encoding="utf-8")
            return f"Saved {shown} in the Alter Ego folder."
        # make_folder
        target.mkdir(parents=True, exist_ok=True)
        return f"Made the folder {shown} in the Alter Ego folder."
