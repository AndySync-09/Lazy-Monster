"""Brain-Break: when the internet goes away, the monster keeps working on its own brain.

A light check every 20 s (a TCP connection to a couple of well-known hosts; nothing is sent).
Two misses in a row = offline: the monster says so, the status bar shows "Brain-Break", and
requests go to the on-PC quick brain (or to your local model if that's your main brain).
Anything that truly needs the internet is kept, and offered again when the connection is back."""
import socket
import threading
import time
from typing import Callable, List

HOSTS = [("1.1.1.1", 443), ("8.8.8.8", 443), ("208.67.222.222", 443)]


def online(timeout: float = 2.0) -> bool:
    for host, port in HOSTS:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class BrainBreak:
    def __init__(self, on_change: Callable[[bool], None], check: Callable[[], bool] = online, every: float = 20.0):
        self.on_change, self.check, self.every = on_change, check, every
        self.offline = False
        self.waiting: List[str] = []          # requests that need the internet, kept for later
        self._misses = 0

    def tick(self) -> None:
        up = self.check()
        if up:
            self._misses = 0
            if self.offline:
                self.offline = False
                self.on_change(False)
        else:
            self._misses += 1
            if self._misses >= 2 and not self.offline:
                self.offline = True
                self.on_change(True)

    def run(self, stop: threading.Event) -> None:
        def loop():
            while not stop.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                stop.wait(self.every if not self.offline else 8.0)
        threading.Thread(target=loop, daemon=True, name="lazymonster-brainbreak").start()
