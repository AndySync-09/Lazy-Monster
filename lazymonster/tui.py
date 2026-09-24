"""The monster's terminal look: colours, the mascot, a live mic meter, and a
recorder that listens for you (no pressing Enter before every take)."""
import os
import random
import sys
import time

import numpy as np

V, L, P, D, B, R = "\033[38;5;141m", "\033[38;5;191m", "\033[38;5;205m", "\033[2m", "\033[1m", "\033[0m"

AWAKE = [
    "      /\\           /\\",
    "     /  \\_________/  \\",
    "    |    (o)   (o)    |",
    "    |        v        |",
    "     \\_______________/",
]
SLEEPY = [
    "      /\\           /\\      z",
    "     /  \\_________/  \\   z",
    "    |    (-)   (-)    |  ",
    "    |        o        |",
    "     \\_______________/",
]
CHEERS = ["Got it.", "Crisp.", "Nom. Tasty syllables.", "The monster approves.", "Nice one.", "Clear as a bell.",
          "Yep, that's you.", "Lovely."]


def enable() -> None:
    """Turn on colours in the Windows console (Windows Terminal already has them)."""
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def monster(sleepy: bool = False, colour: str = V) -> None:
    for line in (SLEEPY if sleepy else AWAKE):
        print(colour + line + R)


def title(text: str) -> None:
    print(f"\n{B}{V}{text}{R}")


def say(text: str) -> None:
    print(f"  {text}")


def dim(text: str) -> None:
    print(f"  {D}{text}{R}")


def ok(text: str) -> None:
    print(f"  {L}\u2713{R} {text}")


def warn(text: str) -> None:
    print(f"  {P}!{R} {text}")


def dots(done: int, total: int) -> str:
    return " ".join((L + "\u25cf" + R) if i < done else (D + "\u25cb" + R) for i in range(total))


def meter(level: float, width: int = 26) -> str:
    n = int(min(1.0, level * 9) * width)
    return L + "\u2588" * n + R + D + "\u00b7" * (width - n) + R


def cheer() -> str:
    return random.choice(CHEERS)


class Recorder:
    """Opens the mic once; each take waits for you to speak, shows a live meter,
    and stops by itself when you pause."""

    def __init__(self, device=None):
        import sounddevice as sd
        self.sd, self.device, self.floor = sd, device, 0.004

    def _stream(self):
        return self.sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=800, device=self.device)

    def calibrate(self, seconds: float = 1.0) -> float:
        with self._stream() as s:
            x, _ = s.read(int(16000 * seconds))
        self.floor = max(0.002, float(np.sqrt(np.mean(x[:, 0] ** 2))))
        return self.floor

    def take(self, label: str, max_s: float = 5.0, min_speech: float = 0.35, end_silence: float = 0.6,
             wait_s: float = 6.0):
        """Returns the clip (with a little padding), or None if it didn't hear you."""
        thr = max(0.012, self.floor * 3.5)
        blocks, speaking, spoken, quiet, waited, level = [], False, 0.0, 0.0, 0.0, 0.0
        with self._stream() as s:
            while True:
                x, _ = s.read(800)
                b = x[:, 0].copy()
                rms = float(np.sqrt(np.mean(b ** 2)))
                level = max(rms, level * 0.8)
                blocks.append(b)
                if rms > thr:
                    speaking, quiet = True, 0.0
                    spoken += 0.05
                elif speaking:
                    quiet += 0.05
                else:
                    waited += 0.05
                    blocks = blocks[-8:]                       # keep 0.4 s before you start
                state = f"{P}\u25cf listening{R}" if speaking else f"{D}\u25cb waiting{R}"
                sys.stdout.write(f"\r  {label}  {meter(level)}  {state}   ")
                sys.stdout.flush()
                if speaking and quiet >= end_silence and spoken >= min_speech:
                    break
                if speaking and (spoken + quiet) >= max_s:
                    break
                if not speaking and waited >= wait_s:
                    sys.stdout.write("\r" + " " * 90 + "\r")
                    return None
        sys.stdout.write("\r" + " " * 90 + "\r")
        return np.concatenate(blocks)

    def timed(self, label: str, seconds: float):
        """Record for a fixed time (normal talk, room noise) with a countdown."""
        out = []
        with self._stream() as s:
            t_end = time.time() + seconds
            while time.time() < t_end:
                x, _ = s.read(800)
                b = x[:, 0].copy()
                out.append(b)
                left = max(0, t_end - time.time())
                sys.stdout.write(f"\r  {label}  {meter(float(np.sqrt(np.mean(b ** 2))))}  {left:4.1f} s   ")
                sys.stdout.flush()
        sys.stdout.write("\r" + " " * 90 + "\r")
        return np.concatenate(out)
