"""Deterministic command grammar. Zero models, sub-millisecond."""
import re
from typing import Callable, List, Optional, Tuple

from .intents import Intent
from .normalize import normalize

SETTINGS_PAGES = {
    "bluetooth": "bluetooth", "wifi": "network-wifi", "wi fi": "network-wifi", "network": "network",
    "display": "display", "screen": "display", "sound": "sound", "audio": "sound",
    "update": "windowsupdate", "updates": "windowsupdate", "windows update": "windowsupdate",
    "battery": "batterysaver", "power": "powersleep", "privacy": "privacy",
    "personalization": "personalization", "background": "personalization-background",
    "apps": "appsfeatures", "mouse": "mousetouchpad", "keyboard": "keyboard",
}

Rule = Tuple[str, "re.Pattern[str]", Callable[[re.Match], dict]]


def _r(p: str) -> "re.Pattern[str]":
    return re.compile(r"^(?:" + p + r")$")


def _step(m: re.Match) -> dict:
    g = m.groupdict().get("n")
    return {"step": min(int(g), 100)} if g else {}


_THE = r"(?:the |this |my )?"
_PC = r"(?:computer|pc|laptop|system|machine)"

RULES: List[Rule] = [
    ("confirm_yes", _r(r"yes|yeah|yep|yup|confirm|do it|go ahead|sure"), lambda m: {}),
    ("confirm_no", _r(r"no|nope|(?:cancel|stop|abort|halt)(?: it| that| now| everything)?|never ?mind|dont"), lambda m: {}),
    ("volume_set", _r(rf"(?:set |change |turn |put )?{_THE}(?:volume|sound) (?:to |at )?(?P<n>\d{{1,3}})(?: percent)?"),
     lambda m: {"level": min(int(m["n"]), 100)}),
    ("volume_up", _r(rf"(?:turn |crank )?{_THE}(?:volume|sound) up(?: by (?P<n>\d{{1,3}})(?: percent)?)?|louder|turn it up|increase {_THE}volume(?: by (?P<n2>\d{{1,3}}))?"),
     lambda m: {"step": min(int(m["n"] or m["n2"]), 100)} if (m["n"] or m["n2"]) else {}),
    ("volume_down", _r(rf"(?:turn )?{_THE}(?:volume|sound) down(?: by (?P<n>\d{{1,3}})(?: percent)?)?|quieter|turn it down|decrease {_THE}volume(?: by (?P<n2>\d{{1,3}}))?|lower {_THE}volume"),
     lambda m: {"step": min(int(m["n"] or m["n2"]), 100)} if (m["n"] or m["n2"]) else {}),
    ("unmute", _r(rf"unmute(?: {_THE}(?:sound|audio|volume|speakers?))?"), lambda m: {}),
    ("mute", _r(rf"mute(?: {_THE}(?:sound|audio|volume|speakers?))?|be quiet|silence"), lambda m: {}),
    ("media_next", _r(r"next(?: song| track)?|skip(?: (?:this )?(?:song|track))?|play next"), lambda m: {}),
    ("media_prev", _r(r"previous(?: song| track)?|last (?:song|track)|go back a (?:song|track)"), lambda m: {}),
    ("media_play_pause", _r(r"play|pause|resume|(?:play|pause|resume|stop) (?:the )?(?:music|song|video|media|playback)"), lambda m: {}),
    ("lock", _r(rf"lock(?: {_THE}(?:screen|{_PC}))?|lock it"), lambda m: {}),
    ("screenshot", _r(r"(?:take |grab )?(?:a )?screen ?shot|capture (?:the )?screen|print screen"), lambda m: {}),
    ("new_tab", _r(r"(?:open )?(?:a )?new tab"), lambda m: {}),
    ("close_tab", _r(rf"close {_THE}tab"), lambda m: {}),
    ("minimize", _r(rf"minimi[sz]e(?: {_THE}window)?|hide {_THE}window"), lambda m: {}),
    ("maximize", _r(rf"maximi[sz]e(?: {_THE}window)?|full ?screen(?: {_THE}window)?"), lambda m: {}),
    ("show_desktop", _r(r"show (?:the )?desktop|go to (?:the )?desktop|minimi[sz]e everything"), lambda m: {}),
    ("switch_window", _r(r"switch (?:the )?(?:windows?|apps?)|alt tab|next window"), lambda m: {}),
    ("brightness_set", _r(rf"(?:set |change |turn )?{_THE}brightness (?:to |at )?(?P<n>\d{{1,3}})(?: percent)?"),
     lambda m: {"level": min(int(m["n"]), 100)}),
    ("sleep", _r(rf"put {_THE}{_PC} to sleep|sleep {_THE}{_PC}|{_PC} sleep"), lambda m: {}),
    ("move_monster", _r(r"(?:move|go|slide|scoot)(?: yourself| over)?(?: to)?(?: the)? (left|right)(?: side| corner)?"),
     lambda m: {"side": m.group(1)}),
    ("exit_app", _r(r"(?:(?:you can|can you|please|now|okay|ok|just|man|dude)\s+)*(?:go\s+)?(?:to\s+|back to\s+)?sleep(?:\s+(?:now|please|man|dude))*"
                    r"|exit|quit|good ?night|good ?bye|bye(?: bye)?|nap time|take a nap|stop listening|that'?s all(?: for now)?"
                    r"|(?:thanks|thank you)[, ]+that'?s (?:all|it)|we'?re done(?: for now)?"), lambda m: {}),
    ("shutdown", _r(rf"shut ?down(?: {_THE}{_PC})?|turn off {_THE}{_PC}|power off(?: {_THE}{_PC})?"), lambda m: {}),
    ("restart", _r(rf"restart(?: {_THE}{_PC})?|reboot(?: {_THE}{_PC})?"), lambda m: {}),
    ("open_settings", _r(r"open (?P<p>[a-z ]+?) settings|(?:open )?settings for (?P<p2>[a-z ]+)|open settings"),
     lambda m: {"page": (m["p"] or m["p2"] or "").strip()}),
    ("search_web", _r(r"(?:search(?: the web)?(?: for)?|google|look up) (?P<q>.+)"), lambda m: {"query": m["q"]}),
    ("type_text", _r(r"(?:type|dictate) (?P<t>.+)"), lambda m: {"text": m["t"]}),
    ("close_app", _r(r"(?:close|quit|exit|kill) (?P<a>.+)"), lambda m: {"app": m["a"]}),
    ("open_app", _r(r"(?:open|launch|start|run|go to) (?P<a>.+)"), lambda m: {"app": m["a"]}),
]


class Grammar:
    """resolve_app(name) -> canonical app key or None. Unresolvable apps don't match,
    so they fall through to the fallback instead of failing silently."""

    def __init__(self, resolve_app: Optional[Callable[[str], Optional[str]]] = None):
        self.resolve_app = resolve_app or (lambda a: a)

    def parse(self, text: str) -> Optional[Intent]:
        t = normalize(text)
        if not t:
            return None
        for name, pat, extract in RULES:
            m = pat.match(t)
            if not m:
                continue
            slots = extract(m)
            if name == "open_settings":
                page = slots.get("page", "")
                if page and page not in SETTINGS_PAGES:
                    continue
                slots = {"page": SETTINGS_PAGES.get(page, "")}
            if name in ("open_app", "close_app"):
                key = self.resolve_app(slots["app"].strip())
                if not key:
                    return None
                slots = {"app": key}
            return Intent.make(name, **slots)
        return None
