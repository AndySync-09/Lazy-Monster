"""On-device "Hey Monster" wake-word detector.

Features: openWakeWord's melspectrogram + speech-embedding models (Apache 2.0),
compiled with OpenVINO at fixed shapes so they run on the Intel NPU (GPU/CPU
fallback). Classifier: a small logistic head over the last 16 embeddings
(~1.3 s), trained on this machine by `monster wake-train` from your own
recordings plus synthetic Kokoro voices. Nothing leaves the PC."""
import collections
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .models import download, models_dir

OWW = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
CHUNK, MEL_IN, WIN, CTX = 1280, 1760, 76, 16


def feature_paths():
    d = models_dir() / "wakeword"
    d.mkdir(parents=True, exist_ok=True)
    return (download(OWW + "melspectrogram.onnx", d / "melspectrogram.onnx", "wake features (mel)"),
            download(OWW + "embedding_model.onnx", d / "embedding_model.onnx", "wake features (embedding)"))


def model_path() -> Path:
    return models_dir() / "wakeword" / "hey_monster.npz"


def npu_friendly(model):
    """The NPU compiler rejects some Maximum/Minimum forms (seen on Core Ultra:
    'failed to legalize IE.Maximum'). Rewrite them exactly: constant bounds become
    Clamp, tensor-tensor becomes a + relu(b - a). Equal on CPU (float rounding aside)."""
    import openvino.opset13 as ops
    for node in list(model.get_ops()):
        t = node.get_type_name()
        if t not in ("Maximum", "Minimum"):
            continue
        a, b = node.input_value(0), node.input_value(1)
        consts = [i for i, v in enumerate((a, b)) if v.get_node().get_type_name() == "Constant"]
        if consts:
            cval = (a, b)[consts[0]].get_node().get_data()
            x = (a, b)[1 - consts[0]]
            if cval.size == 1:
                v = float(np.clip(float(cval.reshape(-1)[0]), -3.0e38, 3.0e38))
                new = ops.clamp(x, v, 3.0e38) if t == "Maximum" else ops.clamp(x, -3.0e38, v)
                node.output(0).replace(new.output(0))
                continue
        new = (ops.add(a, ops.relu(ops.subtract(b, a))) if t == "Maximum"
               else ops.subtract(a, ops.relu(ops.subtract(a, b))))
        node.output(0).replace(new.output(0))
    model.validate_nodes_and_infer_types()
    return model


class _Ort:
    """ONNX Runtime stand-in with the same infer() shape as an OpenVINO request."""

    def __init__(self, path):
        import onnxruntime as ort
        self.s = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self.name = self.s.get_inputs()[0].name

    def infer(self, feed):
        return {"out": self.s.run(None, {self.name: next(iter(feed.values()))})[0]}


class Features:
    """Fixed-shape models: [1,1760] audio -> mel frames; [1,76,32,1] mel -> 96-d embedding.
    Each model picks its own device, so the embedding network can stay on the NPU
    even if the small mel front end has to fall back. Without OpenVINO (macOS)
    both run on ONNX Runtime on the CPU."""

    def __init__(self, device: str = "auto"):
        try:
            import openvino as ov
        except Exception:
            ov = None
        if ov is None:
            mel_p, emb_p = feature_paths()
            self.errors = {}
            self.mel_c, self.emb_c = _Ort(mel_p), _Ort(emb_p)
            self.mel_device = self.emb_device = self.device = "CPU"
            return
        from . import npu
        mel_p, emb_p = feature_paths()
        core = ov.Core()
        mel, emb = core.read_model(str(mel_p)), core.read_model(str(emb_p))
        mel.reshape({mel.inputs[0]: [1, MEL_IN]})
        emb.reshape({emb.inputs[0]: [1, WIN, 32, 1]})
        npu_friendly(mel)
        avail = npu.devices()
        order = ["NPU", "GPU", "CPU"] if device == "auto" else [device.upper(), "CPU"]
        order = [d for d in order if d == "CPU" or any(k.startswith(d) for k in avail)]
        self.errors = {}
        cache = {"CACHE_DIR": str(models_dir() / "ov_cache")}

        def compile_first(model, name):
            for d in order:
                try:
                    return core.compile_model(model, d, cache).create_infer_request(), d
                except Exception as e:
                    self.errors[f"{name}@{d}"] = f"{type(e).__name__}: {str(e).splitlines()[0][:120]}"
            raise RuntimeError(f"wake features could not compile: {self.errors}")

        # The mel front end takes log(max(x, 1e-10)); in the NPU's FP16, 1e-10 underflows to 0
        # and log(0) = -inf, which silently ruins the features. It is tiny, so it runs on CPU.
        self.mel_c = core.compile_model(mel, "CPU").create_infer_request()
        self.mel_device = "CPU"
        self.emb_c, self.emb_device = compile_first(emb, "embedding")
        if self.emb_device != "CPU":
            # The detector was trained on CPU features; make sure this device reproduces them.
            ref = core.compile_model(emb, "CPU").create_infer_request()
            x = np.random.default_rng(1).normal(2.0, 1.0, (1, WIN, 32, 1)).astype(np.float32)
            a = np.squeeze(list(ref.infer({0: x}).values())[0])
            b = np.squeeze(list(self.emb_c.infer({0: x}).values())[0])
            self.agreement = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
            if not np.isfinite(self.agreement) or self.agreement < 0.99:
                self.errors[f"embedding@{self.emb_device}"] = f"output differs from CPU (cosine {self.agreement:.3f})"
                self.emb_c, self.emb_device = ref, "CPU"
        self.device = self.emb_device if self.emb_device == "CPU" else f"{self.emb_device} (front end on CPU)"

    def mel(self, x1760: np.ndarray) -> np.ndarray:
        out = self.mel_c.infer({0: x1760.reshape(1, MEL_IN).astype(np.float32)})
        spec = np.squeeze(list(out.values())[0])
        return spec / 10 + 2                                    # openWakeWord's transform

    def embed(self, mel76: np.ndarray) -> np.ndarray:
        out = self.emb_c.infer({0: mel76.reshape(1, WIN, 32, 1).astype(np.float32)})
        return np.squeeze(list(out.values())[0]).reshape(96)


class Stream:
    """Streaming features: every 80 ms of audio yields one 96-d embedding; the
    classifier looks at the last 16 (about 1.3 s)."""

    def __init__(self, feats: Features):
        self.f = feats
        self.raw = np.zeros(MEL_IN, dtype=np.float32)
        self.pending = np.zeros(0, dtype=np.float32)
        self.mel = np.ones((WIN, 32), dtype=np.float32)
        self.emb = np.zeros((CTX, 96), dtype=np.float32)
        self.count = 0

    def push(self, audio: np.ndarray):
        """audio: float32 in [-1, 1] at 16 kHz. Yields feature windows (16, 96)."""
        x = np.concatenate([self.pending, (audio * 32767.0).astype(np.float32)])
        while len(x) >= CHUNK:
            chunk, x = x[:CHUNK], x[CHUNK:]
            self.raw = np.concatenate([self.raw[CHUNK:], chunk])
            self.mel = np.vstack([self.mel, self.f.mel(self.raw)])[-(WIN + 24):]
            self.emb = np.vstack([self.emb[1:], self.f.embed(self.mel[-WIN:])])
            self.count += 1
            yield self.emb
        self.pending = x


class Head:
    def __init__(self, w, b, mean, std, threshold):
        self.w, self.b, self.mean, self.std, self.threshold = w, float(b), mean, std, float(threshold)

    def score(self, window: np.ndarray) -> float:
        z = (window.reshape(-1) - self.mean) / self.std
        return float(1 / (1 + np.exp(-(z @ self.w + self.b))))

    def save(self, path: Path, **meta):
        np.savez(path, w=self.w, b=self.b, mean=self.mean, std=self.std, threshold=self.threshold,
                 meta=np.array(repr(meta)))

    @staticmethod
    def load(path: Path) -> "Head":
        d = np.load(path)
        return Head(d["w"], d["b"], d["mean"], d["std"], d["threshold"])


def train_head(pos: np.ndarray, neg: np.ndarray, epochs: int = 400, l2: float = 1e-3, lr: float = 0.1,
               pos_weight: float = 4.0) -> Head:
    """Logistic regression with class weighting (false wakes cost more than misses)."""
    X = np.vstack([pos.reshape(len(pos), -1), neg.reshape(len(neg), -1)]).astype(np.float64)
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    mean, std = X.mean(0), X.std(0) + 1e-6
    Z = (X - mean) / std
    wts = np.where(y == 1, pos_weight * len(neg) / max(len(pos), 1), 1.0)
    wts = wts / wts.mean()
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = (p - y) * wts
        w -= lr * (Z.T @ g / len(y) + l2 * w)
        b -= lr * g.mean()
    return Head(w.astype(np.float32), b, mean.astype(np.float32), std.astype(np.float32), 0.5)


def pick_threshold(head: Head, pos: np.ndarray, neg: np.ndarray, max_fpr: float = 0.002) -> dict:
    sp = np.array([head.score(x) for x in pos])
    sn = np.array([head.score(x) for x in neg])
    q_neg = float(np.quantile(sn, 1 - max_fpr)) + 1e-3 if len(sn) else 0.5
    p10 = float(np.quantile(sp, 0.10)) if len(sp) else q_neg
    # at least above the noisy negatives; then move halfway toward the positives for margin
    thr = min(0.95, max(0.5, q_neg, (q_neg + p10) / 2))
    head.threshold = thr
    return {"threshold": round(thr, 3), "recall": round(float((sp >= thr).mean()), 3) if len(sp) else 0.0,
            "false_positive_rate": round(float((sn >= thr).mean()), 4) if len(sn) else 0.0}


class Detector:
    """Runs the stream on a background thread; calls on_wake when the score
    stays above threshold for 2 consecutive 80 ms steps, then cools down."""

    def __init__(self, feats: Features, head: Head, on_wake: Callable[[float], None],
                 sensitivity: float = 0.0, clock=time.monotonic):
        self.stream, self.head, self.on_wake = Stream(feats), head, on_wake
        # the trained threshold, adjustable with wake_sensitivity; three hits in a row (240 ms)
        self.threshold = min(0.97, max(0.5, head.threshold - sensitivity))
        self.peak = 0.0
        self.q: "collections.deque" = collections.deque(maxlen=200)
        self.clock, self.hits, self.cool_until = clock, 0, 0.0
        self.paused = False
        self.last_score = 0.0
        self._ev = threading.Event()
        threading.Thread(target=self._loop, daemon=True, name="lazymonster-wake").start()

    def feed(self, block: np.ndarray) -> None:
        self.q.append(block)
        self._ev.set()

    def _loop(self):
        while True:
            self._ev.wait(0.5)
            self._ev.clear()
            while self.q:
                block = self.q.popleft()
                for window in self.stream.push(block):
                    if self.paused:
                        continue
                    s = self.head.score(window)
                    self.last_score = s
                    self.peak = max(self.peak, s)
                    now = self.clock()
                    self.hits = self.hits + 1 if s >= self.threshold else 0
                    if self.hits >= 3 and now >= self.cool_until:
                        self.hits, self.cool_until = 0, now + 2.0
                        try:
                            self.on_wake(s)
                        except Exception:
                            pass


def load_detector(on_wake, device: str = "auto", sensitivity: float = 0.0) -> Optional[Detector]:
    p = model_path()
    if not p.exists():
        return None
    return Detector(Features(device), Head.load(p), on_wake, sensitivity)
