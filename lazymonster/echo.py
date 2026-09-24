"""Stops the monster from hearing itself.

Loud speakers (a TV over HDMI, a soundbar, Bluetooth) add delay and volume, so the end of
the monster's own sentence can reach the microphone after it stopped talking, get transcribed,
and land in a running task as if you'd said it. Three defences:

1. Echo tail: the microphone stays shut a little longer after it speaks, longer on
   HDMI / TV / Bluetooth outputs, whose sound arrives late.
2. Words it just said don't count: anything heard that is mostly the same words as what it
   said in the last few seconds is dropped.
3. On loud external speakers, interrupting it by talking requires the voice lock to say
   it's you (not just "not clearly someone else")."""
import re
import time
from collections import deque
from typing import Optional

LATE_OUTPUTS = re.compile(r"hdmi|display audio|nvidia high definition|\btv\b|television|bluetooth|soundbar|"
                          r"avr|receiver|monitor|dell|lg |samsung|sony|bose|jbl", re.I)
HEADPHONES = re.compile(r"headphone|headset|earbud|airpods|buds", re.I)
_WORD = re.compile(r"[a-z0-9']+")


def output_device_name() -> str:
    try:
        import sounddevice as sd
        return str(sd.query_devices(kind="output").get("name", ""))
    except Exception:
        return ""


def profile(name: str = None) -> dict:
    """How late and loud its own voice comes back, by the kind of output device."""
    name = output_device_name() if name is None else name
    if HEADPHONES.search(name):
        return {"kind": "headphones", "tail": 0.15, "loud": False, "device": name}
    if LATE_OUTPUTS.search(name):
        return {"kind": "external", "tail": 0.9, "loud": True, "device": name}
    return {"kind": "laptop", "tail": 0.35, "loud": False, "device": name}


class EchoGuard:
    def __init__(self, window: float = 8.0, clock=time.monotonic):
        self.window, self.clock = window, clock
        self.said = deque(maxlen=12)                 # (time it finished, set of words)

    def record(self, text: str) -> None:
        words = set(_WORD.findall((text or "").lower()))
        if words:
            self.said.append((self.clock(), words))

    def is_echo(self, heard: str) -> bool:
        words = [w for w in _WORD.findall((heard or "").lower()) if w not in ("hey", "monster")]
        if not words:
            return False
        now = self.clock()
        recent = set().union(*[w for t, w in self.said if now - t < self.window]) if self.said else set()
        if not recent:
            return False
        overlap = sum(1 for w in words if w in recent) / len(words)
        return overlap >= (1.0 if len(words) <= 2 else 0.7)
