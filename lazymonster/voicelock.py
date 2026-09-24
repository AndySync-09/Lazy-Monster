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

    def embed(self, audio: np.ndarray) -> np.ndarray:
        s = self.ex.create_stream()
        s.accept_waveform(16000, np.asarray(audio, dtype=np.float32))
        s.input_finished()
        e = np.array(self.ex.compute(s), dtype=np.float32)
        return e / (np.linalg.norm(e) + 1e-9)

    def enroll(self, clips: List[np.ndarray]) -> dict:
        embs = np.array([self.embed(c) for c in clips])
        c = embs.mean(0)
        self.centroid = c / np.linalg.norm(c)
        # leave-one-out: how similar is each of your clips to the rest of you?
        self_scores = []
        for i in range(len(embs)):
            rest = np.delete(embs, i, 0).mean(0)
            self_scores.append(float(embs[i] @ (rest / np.linalg.norm(rest))))
        self.threshold = float(np.clip(min(self_scores) - 0.15, 0.5, 0.72))
        return {"self_min": round(min(self_scores), 3), "self_mean": round(float(np.mean(self_scores)), 3),
                "threshold": round(self.threshold, 3)}

    def save(self) -> Path:
        p = print_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez(p, centroid=self.centroid, threshold=self.threshold)
        return p

    def load(self) -> bool:
        p = print_path()
        if not p.exists():
            return False
        d = np.load(p)
        self.centroid, self.threshold = d["centroid"], float(d["threshold"])
        return True

    def check(self, audio: np.ndarray) -> Tuple[bool, float]:
        """(is it you?, similarity). Very short audio can't be judged: it passes."""
        if self.centroid is None:
            return True, 1.0
        if len(audio) < 16000 * 0.6:
            return True, -1.0
        score = float(self.embed(audio) @ self.centroid)
        return score >= self.threshold, score


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
        audio = np.frombuffer(inp.read(n), dtype=np.float32)
        try:
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

    def check(self, audio: np.ndarray):
        a = np.asarray(audio, dtype=np.float32)
        if len(a) < 16000 * 0.6:
            return True, -1.0
        with self._lock:
            if self.p.poll() is not None:
                return True, -1.0
            box = {}

            def read():
                box["line"] = self.p.stdout.readline()
            t = _th.Thread(target=read, daemon=True)
            try:
                data = a.tobytes()
                self.p.stdin.write(len(data).to_bytes(4, "little") + data)
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
