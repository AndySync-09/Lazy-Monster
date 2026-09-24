"""Typed tool schema. Every action Lazy-Monster can take is declared here.
Nothing outside this table can execute — not the grammar, not the planner,
not text produced by a model."""
from dataclasses import dataclass, field
from typing import Any, Dict

# slot spec: (type, min, max)  for int = value range, for str = length range
LEVEL = (int, 0, 100)
NAME = (str, 1, 120)
TEXT = (str, 1, 20000)

# grammar=True: reachable by the instant grammar. agent=True: planner may use it.
# confirm: always ask "yes" first. early: may fire before end of speech.
SCHEMA: Dict[str, Dict[str, Any]] = {
    "volume_set":     {"slots": {"level": LEVEL}, "confirm": False, "early": True, "desc": "Set system volume percent"},
    "volume_up":      {"slots": {"step": LEVEL},  "optional": ["step"], "confirm": False, "early": True, "desc": "Raise volume by step percent"},
    "volume_down":    {"slots": {"step": LEVEL},  "optional": ["step"], "confirm": False, "early": True, "desc": "Lower volume by step percent"},
    "mute":           {"slots": {}, "confirm": False, "early": True, "desc": "Mute audio"},
    "unmute":         {"slots": {}, "confirm": False, "early": True, "desc": "Unmute audio"},
    "media_play_pause": {"slots": {}, "confirm": False, "early": True, "desc": "Toggle media play/pause"},
    "media_next":     {"slots": {}, "confirm": False, "early": True, "desc": "Next track"},
    "media_prev":     {"slots": {}, "confirm": False, "early": True, "desc": "Previous track"},
    "lock":           {"slots": {}, "confirm": False, "early": True, "desc": "Lock the PC"},
    "screenshot":     {"slots": {}, "confirm": False, "early": True, "desc": "Save a screenshot to Pictures\\Screenshots"},
    "new_tab":        {"slots": {}, "confirm": False, "early": True, "desc": "Ctrl+T in the focused app"},
    "close_tab":      {"slots": {}, "confirm": False, "early": True, "desc": "Ctrl+W in the focused app"},
    "minimize":       {"slots": {}, "confirm": False, "early": True, "desc": "Minimize focused window"},
    "maximize":       {"slots": {}, "confirm": False, "early": True, "desc": "Maximize focused window"},
    "show_desktop":   {"slots": {}, "confirm": False, "early": True, "desc": "Show desktop"},
    "switch_window":  {"slots": {}, "confirm": False, "early": True, "desc": "Alt+Tab"},
    "brightness_set": {"slots": {"level": LEVEL}, "confirm": False, "early": True, "desc": "Set built-in display brightness percent"},
    "open_settings":  {"slots": {"page": (str, 0, 40)}, "confirm": False, "early": True, "desc": "Open a Windows Settings page (ms-settings id, empty for home)"},
    "open_app":       {"slots": {"app": NAME}, "confirm": False, "early": False, "desc": "Open an installed app or known site by name"},
    "close_app":      {"slots": {"app": NAME}, "confirm": False, "early": False, "desc": "Ask an app to close (it may prompt to save)"},
    "search_web":     {"slots": {"query": (str, 1, 300)}, "confirm": False, "early": False, "desc": "Web search in the default browser"},
    "type_text":      {"slots": {"text": TEXT}, "confirm": False, "early": False, "desc": "Type text into the focused window (not terminals or VS Code; use code_write_file for code)"},
    "sleep":          {"slots": {}, "confirm": True, "early": True, "desc": "Sleep the PC"},
    "exit_app":       {"slots": {}, "confirm": False, "early": True, "internal": True},
    "move_monster":   {"slots": {"side": (str, 4, 6)}, "confirm": False, "early": True, "internal": True},
    "shutdown":       {"slots": {}, "confirm": True, "early": True, "desc": "Shut down the PC"},
    "restart":        {"slots": {}, "confirm": True, "early": True, "desc": "Restart the PC"},
    "confirm_yes":    {"slots": {}, "confirm": False, "early": True, "internal": True},
    "confirm_no":     {"slots": {}, "confirm": False, "early": True, "internal": True},
    # ---- agent tools (agent loop only) ------------------------------------
    "list_windows":   {"slots": {}, "confirm": False, "early": False, "agent": True, "desc": "List open windows as 'title | process'"},
    "focus_window":   {"slots": {"title": NAME}, "confirm": False, "early": False, "agent": True, "desc": "Bring the window whose title best matches to the front"},
    "read_window":    {"slots": {"title": (str, 0, 120)}, "optional": ["title"], "confirm": False, "early": False, "agent": True,
                       "desc": "Read the named controls of a window (default: the focused one) to see what is on screen"},
    "read_text":      {"slots": {"title": (str, 0, 120)}, "optional": ["title"], "confirm": False, "early": False, "agent": True,
                       "desc": "Read the text content of a document window (default: the one you are working in)"},
    "write_in_app":   {"slots": {"app": NAME, "text": (str, 1, 100000)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Fastest way to write text in a text app: opens the app, makes a new document, pastes the text and verifies it"},
    "click":          {"slots": {"name": NAME, "window": (str, 0, 120)}, "optional": ["window"], "confirm": False, "early": False, "agent": True,
                       "desc": "Click the button/menu/control with this visible name (optionally inside a window whose title matches)"},
    "press_keys":     {"slots": {"keys": (str, 1, 40)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Press an allowed key or shortcut in the focused window, e.g. 'ctrl+s', 'enter', 'tab', 'ctrl+n'"},
    "word_new_document": {"slots": {}, "confirm": False, "early": False, "agent": True, "desc": "Open Microsoft Word with a new blank document"},
    "word_insert_text":  {"slots": {"text": (str, 1, 100000)}, "confirm": False, "early": False, "agent": True,
                          "desc": "Write text into the current Word document, visibly, at the end"},
    "word_save":      {"slots": {"filename": NAME}, "confirm": False, "early": False, "agent": True,
                       "desc": "Save the current Word document as Documents\\LazyMonster\\<filename>.docx"},
    "file_write_text": {"slots": {"filename": NAME, "text": (str, 1, 100000)}, "confirm": False, "early": False, "agent": True,
                        "desc": "Write a .txt or .md file in Documents\\LazyMonster"},
    "code_open":      {"slots": {"project": NAME}, "confirm": False, "early": False, "agent": True,
                       "desc": "Open (creating if needed) the project folder Documents\\LazyMonster\\code\\<project> in VS Code"},
    "code_write_file": {"slots": {"project": NAME, "path": (str, 1, 200), "content": (str, 0, 200000)}, "confirm": False, "early": False, "agent": True,
                        "desc": "Create or replace a source file inside the project and show it being written in VS Code. path is relative, e.g. 'src/app.py'"},
    "code_run":       {"slots": {"project": NAME, "path": (str, 1, 200)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Run a Python file you wrote in the code project, in its own window (the user is asked first). "
                               "Returns errors if it crashes, e.g. a missing package"},
    "code_install":   {"slots": {"project": NAME, "packages": (str, 1, 300)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Install Python packages (space-separated names, e.g. 'pygame') into the project's own "
                               "environment (the user is asked first)"},
    "open_url":       {"slots": {"url": (str, 8, 500)}, "confirm": False, "early": False, "agent": True, "desc": "Open an http(s) URL in the default browser"},
    "ask_user":       {"slots": {"question": (str, 1, 300)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Ask the user a short question and wait for the spoken answer (use for choices that are theirs to make)"},
    "open_file":      {"slots": {"path": (str, 1, 400), "app": (str, 0, 40)}, "optional": ["app"], "confirm": False,
                       "early": False, "agent": True,
                       "desc": "Open a document, web page (.html), PDF, image or deck you made, in its default app or in "
                               "app='chrome'/'edge'/'word'/'powerpoint'. path: full path, or a file name / project/file you created"},
    "export_pdf":     {"slots": {}, "confirm": False, "early": False, "agent": True,
                       "desc": "Save the current Word document as a PDF next to it, and open the PDF"},
    "make_presentation": {"slots": {"filename": NAME, "outline": (str, 1, 20000)}, "confirm": False, "early": False,
                          "agent": True,
                          "desc": "Build a real PowerPoint deck and open it. outline: '# Slide title' lines, each followed by "
                                  "'- bullet' lines (the first slide is the title slide; a line under it is the subtitle)"},
    "web_research":   {"slots": {"question": (str, 1, 500)}, "confirm": False, "early": False, "agent": True,
                       "desc": "Search the web for real and return a sourced summary. Use this for research, news or facts "
                               "instead of answering from memory; search_web only opens a browser page"},
    "go_to_sleep":    {"slots": {}, "confirm": False, "early": False, "agent": True,
                       "desc": "The user wants you to stop listening / go to sleep / be quiet now"},
    "close_all":      {"slots": {}, "confirm": False, "early": False, "agent": True,
                       "desc": "Close everything you opened this session (app windows, Notepad tabs you wrote in, Word documents, "
                               "VS Code windows, programs you ran). It asks the user about unsaved work itself and saves where they say"},
    "recent_work":    {"slots": {}, "confirm": False, "early": False, "agent": True,
                       "desc": "What you and the user worked on in the last week (tasks and files), to recap or resume"},
    "finish":         {"slots": {"summary": (str, 0, 400), "next": (str, 0, 200)}, "optional": ["next"], "confirm": False,
                       "early": False, "agent": True,
                       "desc": "Call when the task is done. summary: one short spoken sentence of what you did. "
                               "next: one concrete, useful follow-up you could do, phrased as a question "
                               "(e.g. 'Want me to save it to your LazyMonster folder?')"},
}

AGENT_TOOLS = [n for n, s in SCHEMA.items() if not s.get("internal") and not s["confirm"]]


@dataclass(frozen=True)
class Intent:
    name: str
    slots: tuple = field(default_factory=tuple)   # sorted (key, value) pairs, hashable
    source: str = "grammar"                       # grammar | openai | jev

    @staticmethod
    def make(tool: str, /, source: str = "grammar", **slots) -> "Intent":
        # tool is positional-only so a slot may itself be called "name" (click)
        return Intent(tool, tuple(sorted(slots.items())), source)

    @property
    def args(self) -> dict:
        return dict(self.slots)

    @property
    def spec(self) -> dict:
        return SCHEMA[self.name]

    def same_as(self, other: "Intent") -> bool:
        return other is not None and self.name == other.name and self.slots == other.slots


class SchemaError(ValueError):
    pass


def validate(name: Any, args: Any, source: str = "openai", allow_refs: bool = True) -> Intent:
    """Type-check a tool call coming from outside the grammar."""
    if not isinstance(name, str) or name not in SCHEMA or SCHEMA[name].get("internal"):
        raise SchemaError(f"unknown tool: {name!r}")
    args = args or {}
    if not isinstance(args, dict):
        raise SchemaError("args must be an object")
    spec = SCHEMA[name]
    extra = set(args) - set(spec["slots"])
    if extra:
        raise SchemaError(f"unexpected args for {name}: {sorted(extra)}")
    clean = {}
    for k, (typ, lo, hi) in spec["slots"].items():
        if k not in args or args[k] is None:
            if k in spec.get("optional", []):
                continue
            raise SchemaError(f"missing arg {k} for {name}")
        v = args[k]
        if typ is int:
            if isinstance(v, bool) or not isinstance(v, int):
                raise SchemaError(f"{name}.{k} must be an integer")
            if not lo <= v <= hi:
                raise SchemaError(f"{name}.{k} out of range {lo}..{hi}")
        else:
            if not isinstance(v, str):
                raise SchemaError(f"{name}.{k} must be a string")
            is_ref = allow_refs and v.strip().startswith("$") and v.strip()[1:].isdigit()
            if not is_ref and not lo <= len(v) <= hi:
                raise SchemaError(f"{name}.{k} length must be {lo}..{hi}")
        clean[k] = v
    return Intent.make(name, source=source, **clean)
