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
    _spec("web_search", "Search the internet. Use for facts you are unsure of or anything recent.",
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
    "call the tool, then say what happened."
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
    ):
        self.folder = Path(folder).expanduser() if folder else default_folder()
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
