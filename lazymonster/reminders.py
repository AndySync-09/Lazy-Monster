"""Reminders that come to you: "remind me about the cafe website meeting at 8 AM".

When one is due, the monster wakes up by itself, says it, and suggests what it could do
next (open the project, update the code, draft an email), then waits for your answer.
It never acts on a suggestion until you pick one. Stored in %APPDATA%\\lazymonster\\reminders.json."""
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable, List, Optional, Tuple

from .config import config_dir

_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45,
        "an": 1, "a": 1, "half an": 0.5}


def _n(s: str) -> float:
    s = s.strip().lower()
    return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else float(_NUM.get(s, 0))


def parse_when(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """'at 8 AM', 'at 8:30 pm', 'at 20:15', 'in 10 minutes', 'in half an hour', 'tomorrow at 9',
    'tonight at 7', 'tomorrow morning', 'at noon'. Returns the next matching moment."""
    now = now or datetime.now()
    t = text.lower().replace(".", "").strip()
    m = re.search(r"\bin (\d+(?:\.\d+)?|an?|half an|one|two|three|five|ten|fifteen|twenty|thirty|forty five) "
                  r"(minutes?|mins?|hours?|hrs?)\b", t)
    if m:
        n = _n(m.group(1))
        return now + (timedelta(hours=n) if m.group(2).startswith("h") else timedelta(minutes=n))
    day = now.date()
    tomorrow = bool(re.search(r"\btomorrow\b", t))
    if tomorrow:
        day = day + timedelta(days=1)
    hour = minute = None
    ampm = None
    if re.search(r"\bnoon\b|\bmidday\b", t):
        hour, minute = 12, 0
    elif re.search(r"\bmidnight\b", t):
        hour, minute = 0, 0
    else:
        m = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a m|p m)?\b", t)
        if m and (m.group(3) or m.group(2) or re.search(r"\bat\s+\d", t) or tomorrow):
            hour, minute = int(m.group(1)), int(m.group(2) or 0)
            ampm = (m.group(3) or "").replace(" ", "") or None
    if hour is None:
        if re.search(r"\b(tomorrow )?morning\b", t):
            hour, minute = 8, 0
        elif re.search(r"\bafternoon\b", t):
            hour, minute = 14, 0
        elif re.search(r"\b(evening|tonight)\b", t):
            hour, minute = 19, 0
        else:
            return None
    if hour > 23 or minute > 59:
        return None
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif ampm is None and re.search(r"\b(tonight|evening|afternoon)\b", t) and hour < 12:
        hour += 12
    when = datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute)
    if when <= now and not tomorrow:
        if ampm is None and hour < 12 and when + timedelta(hours=12) > now:
            when += timedelta(hours=12)                   # "at 8" said at 10 am means 8 pm
        else:
            when += timedelta(days=1)
    return when


def speak_time(when: datetime, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    clock = when.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
    if when.date() == now.date():
        return f"today at {clock}"
    if when.date() == now.date() + timedelta(days=1):
        return f"tomorrow at {clock}"
    return when.strftime("%A") + f" at {clock}"


def _path():
    return config_dir() / "reminders.json"


def load() -> List[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return []


def save(rows: List[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, indent=1), encoding="utf-8")


_lock = threading.Lock()


def add(what: str, when_text: str, now: Optional[datetime] = None) -> Tuple[Optional[dict], str]:
    when = parse_when(when_text, now)
    if when is None:
        return None, f"I couldn't tell when \"{when_text}\" is. Try \"at 8 AM\" or \"in 20 minutes\"."
    what = re.sub(r"^(to|about|that)\s+", "", what.strip(), flags=re.I).rstrip(" .")
    r = {"id": uuid.uuid4().hex[:8], "what": what, "when": when.isoformat(timespec="minutes"),
         "created": datetime.now().isoformat(timespec="minutes"), "fired": False, "nudged": False}
    with _lock:
        rows = load()
        rows.append(r)
        save(rows)
    return r, f"Okay. I'll remind you about {what} {speak_time(when, now)}."


def upcoming(now: Optional[datetime] = None) -> List[dict]:
    now = now or datetime.now()
    return sorted([r for r in load() if not r["fired"] and datetime.fromisoformat(r["when"]) > now - timedelta(hours=3)],
                  key=lambda r: r["when"])


def describe(now: Optional[datetime] = None) -> str:
    rows = upcoming(now)
    if not rows:
        return "You have no reminders."
    parts = [f"{r['what']} {speak_time(datetime.fromisoformat(r['when']), now)}" for r in rows[:5]]
    return "Your reminders: " + "; ".join(parts) + "."


def cancel(what: str) -> str:
    words = set(re.findall(r"\w+", what.lower())) - {"the", "a", "my", "reminder", "about", "for"}
    with _lock:
        rows = load()
        hit = [r for r in rows if not r["fired"] and (not words or words & set(re.findall(r"\w+", r["what"].lower())))]
        if not hit:
            return "I couldn't find that reminder."
        for r in hit[:1]:
            r["fired"] = True
        save(rows)
    return f"Cancelled the reminder about {hit[0]['what']}."


def mark(rid: str, **fields) -> None:
    with _lock:
        rows = load()
        for r in rows:
            if r["id"] == rid:
                r.update(fields)
        save(rows)


def snooze(minutes: float = 10, now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    rows = [r for r in load() if r["fired"]]
    if not rows:
        return "There's nothing to snooze."
    last = max(rows, key=lambda r: r["when"])
    r, _ = add(last["what"], f"in {int(minutes)} minutes", now)
    return f"Okay, again in {int(minutes)} minutes."


class Scheduler:
    """Checks every 15 s. A reminder missed while the PC was off (up to 3 h late) still fires."""

    def __init__(self, on_fire: Callable[[dict, bool], None], clock=datetime.now):
        self.on_fire, self.clock = on_fire, clock

    def tick(self) -> List[dict]:
        now = self.clock()
        fired = []
        for r in load():
            if r["fired"]:
                continue
            when = datetime.fromisoformat(r["when"])
            if when <= now:
                late = now - when > timedelta(minutes=2)
                mark(r["id"], fired=True)
                if now - when <= timedelta(hours=3):
                    fired.append(r)
                    self.on_fire(r, late)
        return fired

    def run(self, stop: threading.Event) -> None:
        def loop():
            while not stop.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                stop.wait(15)
        threading.Thread(target=loop, daemon=True, name="lazymonster-reminders").start()
