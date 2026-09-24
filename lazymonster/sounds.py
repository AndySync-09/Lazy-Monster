"""Three soft earcons, generated in memory: wake, done, error. Nothing else beeps."""
import io
import math
import os
import struct
import sys
import threading
import wave

_NOTES = {"wake": [(660, .07), (990, .09)], "done": [(880, .06), (1320, .10)], "error": [(440, .09), (330, .12)]}
_cache = {}


def _wav(kind: str, volume: float = 0.18) -> bytes:
    if kind in _cache:
        return _cache[kind]
    sr, frames = 22050, bytearray()
    for f, d in _NOTES[kind]:
        n = int(sr * d)
        for i in range(n):
            env = min(1.0, i / (sr * .008)) * math.exp(-4.0 * i / n)      # soft attack, gentle decay
            frames += struct.pack("<h", int(32767 * volume * env * math.sin(2 * math.pi * f * i / sr)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(bytes(frames))
    _cache[kind] = buf.getvalue()
    return _cache[kind]


def play(kind: str, enabled: bool = True) -> None:
    if not enabled or kind not in _NOTES:
        return
    data = _wav(kind)
    if os.name == "nt":
        import winsound
        threading.Thread(target=winsound.PlaySound, args=(data, winsound.SND_MEMORY), daemon=True).start()
    elif sys.platform == "darwin":
        import subprocess
        import tempfile
        f = os.path.join(tempfile.gettempdir(), f"lazymonster-{kind}.wav")
        if not os.path.exists(f):
            with open(f, "wb") as fh:
                fh.write(data)
        subprocess.Popen(["afplay", f], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
