"""Voice lock: act only on the enrolled voice.

TitaNet-small speaker embeddings (NVIDIA NeMo, via sherpa-onnx, runs on the CPU
in ~50 ms per request). `monster voice-enroll` records a few sentences and saves
a voiceprint (an average embedding plus a calibrated threshold) locally.
Nothing is uploaded. Typed requests and push-to-talk skip the check."""
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .models import download, models_dir

MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "nemo_en_titanet_small.onnx")
ENROLL_SENTENCES = [
    "Hey Monster, open Notepad and write a short note for me.",
    "The quick brown fox jumps over the lazy dog near the river bank.",
    "Please set the volume to thirty percent and play some music.",
    "I'm working on a website for a cafe in Bangalore this week.",
    "Search the web for the latest news and give me a short summary.",
]


def print_path() -> Path:
    return models_dir() / "voicelock" / "voiceprint.npz"


class VoiceLock:
    def __init__(self):
        import sherpa_onnx
        d = models_dir() / "voicelock"
        d.mkdir(parents=True, exist_ok=True)
        m = download(MODEL_URL, d / "nemo_en_titanet_small.onnx", "voice lock model")
        self.ex = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(m), num_threads=1))
        self.centroid, self.threshold = None, 0.6
        self.embs, self.learned = None, []

    def embed(self, audio: np.ndarray) -> np.ndarray:
        s = self.ex.create_stream()
        s.accept_waveform(16000, np.asarray(audio, dtype=np.float32))
        s.input_finished()
        e = np.array(self.ex.compute(s), dtype=np.float32)
        return e / (np.linalg.norm(e) + 1e-9)

    @staticmethod
    def speech(audio: np.ndarray) -> np.ndarray:
        """Just the talking: silence and room noise before and after are cut off."""
        a = np.asarray(audio, dtype=np.float32)
        fr = 320
        if len(a) < fr * 3:
            return a
        e = np.sqrt(np.mean(a[: len(a) // fr * fr].reshape(-1, fr) ** 2, axis=1))
        thr = max(0.008, float(np.percentile(e, 20)) * 3)
        idx = np.where(e > thr)[0]
        if not len(idx):
            return a[:0]
        return a[max(0, idx[0] - 5) * fr:(idx[-1] + 6) * fr]

    def enroll(self, clips: List[np.ndarray]) -> dict:
        embs = np.array([self.embed(self.speech(c)) for c in clips])
        self.embs = embs
        c = embs.mean(0)
        self.centroid = c / np.linalg.norm(c)
        # leave-one-out: how similar is each of your clips to the rest of you?
        self_scores = []
        for i in range(len(embs)):
            rest = np.delete(embs, i, 0).mean(0)
            self_scores.append(float(embs[i] @ (rest / np.linalg.norm(rest))))
        self.threshold = float(np.clip(min(self_scores) - 0.15, 0.45, 0.68))
        return {"self_min": round(min(self_scores), 3), "self_mean": round(float(np.mean(self_scores)), 3),
                "threshold": round(self.threshold, 3)}

    def save(self) -> Path:
        p = print_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez(p, centroid=self.centroid, threshold=self.threshold,
                 embs=self.embs if self.embs is not None else np.zeros((0, len(self.centroid)), np.float32),
                 learned=np.array(self.learned, dtype=np.float32).reshape(-1, len(self.centroid)))
        return p

    def load(self) -> bool:
        p = print_path()
        if not p.exists():
            return False
        d = np.load(p)
        self.centroid, self.threshold = d["centroid"], float(d["threshold"])
        self.embs = d["embs"] if "embs" in d.files and len(d["embs"]) else None
        self.learned = list(d["learned"]) if "learned" in d.files else []
        return True

    def threshold_for(self, seconds: float) -> float:
        """Short commands ("mute") give weaker evidence, so the bar is lower for them:
        measured, "mute" by the enrolled voice scored 0.62-0.70 against a 0.72 bar."""
        return self.threshold - 0.15 * float(np.clip((2.0 - seconds) / 1.4, 0.0, 1.0))

    def score(self, audio: np.ndarray):
        sp = self.speech(audio)
        secs = len(sp) / 16000
        if secs < 0.5:
            return None, secs
        e = self.embed(sp)
        s = float(e @ self.centroid)
        refs = [x for x in (list(self.embs) if self.embs is not None else []) + list(self.learned)]
        if refs:
            best = sorted((float(e @ r) for r in refs), reverse=True)[:2]
            s = max(s, float(np.mean(best)))
        return s, secs

    def check(self, audio: np.ndarray) -> Tuple[bool, float]:
        """(is it you?, similarity). Too little speech to judge: it passes."""
        if self.centroid is None:
            return True, 1.0
        s, secs = self.score(audio)
        if s is None:
            return True, -1.0
        return s >= self.threshold_for(secs), s

    def learn(self, audio: np.ndarray) -> bool:
        """A request that was certainly you (push-to-talk): remember how you sound
        today (your mic, your room), up to the last 20 of them."""
        sp = self.speech(audio)
        if len(sp) < 16000 * 0.8 or self.centroid is None:
            return False
        self.learned = (self.learned + [self.embed(sp)])[-20:]
        base = list(self.embs) if self.embs is not None else [self.centroid]
        c = np.mean(base + self.learned, axis=0)
        self.centroid = c / np.linalg.norm(c)
        self.save()
        return True


def load_lock() -> Optional[VoiceLock]:
    if not print_path().exists():
        return None
    v = VoiceLock()
    v.load()
    return v


# ---- running the check in its own process -------------------------------------------------------
# sherpa-onnx ships its own onnxruntime.dll. Loading it into a process that already has the
# pip onnxruntime (the Kokoro voice) or OpenVINO can crash the whole app on Windows with no
# Python traceback: the background monster just vanished right after loading Whisper.
# So the voice lock lives in a small helper process and answers over a pipe.
import json as _json
import os as _os
import subprocess as _sp
import sys as _sys
import threading as _th


def serve() -> None:
    v = VoiceLock()
    if not v.load():
        _sys.stdout.write("NOPRINT\n"); _sys.stdout.flush()
        return
    out, inp = _sys.stdout.buffer, _sys.stdin.buffer
    out.write(f"READY {v.threshold:.3f}\n".encode()); out.flush()
    while True:
        hdr = inp.read(4)
        if len(hdr) < 4:
            return
        n = int.from_bytes(hdr, "little")
        learn = bool(n & 0x80000000)
        n &= 0x7FFFFFFF
        audio = np.frombuffer(inp.read(n), dtype=np.float32)
        try:
            if learn:
                ok, score = v.learn(audio), 1.0
            else:
                ok, score = v.check(audio)
        except Exception:
            ok, score = True, -1.0
        out.write((_json.dumps({"ok": bool(ok), "score": float(score)}) + "\n").encode()); out.flush()


class VoiceLockProcess:
    """Same check() as VoiceLock, answered by the helper process. If the helper
    is slow or gone, it answers "yes" rather than locking you out."""

    def __init__(self, timeout: float = 3.0):
        flags = 0x08000000 if _os.name == "nt" else 0              # CREATE_NO_WINDOW
        self.p = _sp.Popen([_sys.executable, "-m", "lazymonster.voicelock", "--serve"], stdin=_sp.PIPE,
                           stdout=_sp.PIPE, stderr=_sp.DEVNULL, creationflags=flags)
        first = self.p.stdout.readline().decode(errors="replace").strip()
        if not first.startswith("READY"):
            self.close()
            raise RuntimeError(f"voice lock helper did not start ({first or 'no output'})")
        self.threshold = float(first.split()[1])
        self.timeout, self._lock = timeout, _th.Lock()

    def learn(self, audio: np.ndarray) -> None:
        a = np.asarray(audio, dtype=np.float32)
        if len(a) >= 16000 * 0.8:
            self._ask(a, learn=True)

    def check(self, audio: np.ndarray):
        a = np.asarray(audio, dtype=np.float32)
        if len(a) < 16000 * 0.6:
            return True, -1.0
        return self._ask(a)

    def _ask(self, a, learn: bool = False):
        with self._lock:
            if self.p.poll() is not None:
                return True, -1.0
            box = {}

            def read():
                box["line"] = self.p.stdout.readline()
            t = _th.Thread(target=read, daemon=True)
            try:
                data = a.tobytes()
                self.p.stdin.write((len(data) | (0x80000000 if learn else 0)).to_bytes(4, "little") + data)
                self.p.stdin.flush()
                t.start()
                t.join(self.timeout)
            except Exception:
                return True, -1.0
            if "line" not in box or not box["line"]:
                return True, -1.0
            r = _json.loads(box["line"])
            return bool(r["ok"]), float(r["score"])

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass


def load_lock_process():
    if not print_path().exists():
        return None
    return VoiceLockProcess()


if __name__ == "__main__" and "--serve" in _sys.argv:
    serve()
