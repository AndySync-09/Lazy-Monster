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
