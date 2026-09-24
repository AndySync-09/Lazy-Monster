"""Pass 2 of speech recognition: re-transcribe each finished sentence with a
distilled Whisper model through OpenVINO GenAI, on the NPU when available.
Pass 1 (Moonshine streaming) stays in charge of the wake phrase and instant
commands; this pass decides what the agent actually hears."""
import collections
from pathlib import Path
import re

import numpy as np
import threading
import time
from typing import Iterable, Optional

from .models import models_dir

VOICE_WORDS = ["Lazy Monster", "Notepad", "VS Code", "Bangalore", "Bengaluru", "Koramangala", "Indiranagar",
               "Whitefield", "HSR Layout", "Electronic City", "Jayanagar", "Marathahalli", "Hebbal"]


class AudioTap:
    """Keeps the last `seconds` of microphone audio (16 kHz mono) with timestamps,
    so a finished line can be cut out and re-transcribed."""

    def __init__(self, seconds: float = 40.0, device=None, clock=time.monotonic):
        self.buf = collections.deque()
        self.seconds, self.clock, self.device = seconds, clock, device
        self.lock = threading.Lock()
        self.stream = None
        self.listeners = []                               # e.g. the wake-word detector
        self.speaking = []                                # [start, end] times the monster was talking
        self.tail = 0.35                                  # room echo after it stops

    def start(self):
        import sounddevice as sd

        def cb(indata, frames, t, status):
            now = self.clock()
            block = indata[:, 0].copy()
            for fn in self.listeners:
                fn(block)
            with self.lock:
                self.buf.append((now, block))
                while self.buf and now - self.buf[0][0] > self.seconds:
                    self.buf.popleft()

        self.stream = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=1600,
                                     callback=cb, device=self.device)
        self.stream.start()
        return self

    def mark_speaking(self, on: bool) -> None:
        now = self.clock()
        with self.lock:
            if on:
                self.speaking.append([now, None])
            elif self.speaking and self.speaking[-1][1] is None:
                self.speaking[-1][1] = now
            self.speaking = [iv for iv in self.speaking if iv[1] is None or now - iv[1] < self.seconds]

    def _during_speech(self, t: float, block_s: float) -> bool:
        for s0, s1 in self.speaking:
            end = (s1 if s1 is not None else float("inf")) + self.tail
            if t >= s0 and t - block_s <= end:
                return True
        return False

    def slice(self, t_start: float, t_end: Optional[float] = None, preroll: float = 0.8):
        """Audio of your turn, with the monster's own speech (and its echo) cut out."""
        import numpy as np
        t_end = t_end or self.clock()
        with self.lock:
            parts = [b for (t, b) in self.buf
                     if t_start - preroll <= t <= t_end + 0.2 and not self._during_speech(t, len(b) / 16000)]
        return np.concatenate(parts) if parts else np.zeros(0, dtype="float32")

    def close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()


class WhisperRefiner:
    def __init__(self, repo: str = "OpenVINO/distil-whisper-large-v3-int8-ov", device: str = "auto",
                 vocabulary: Iterable[str] = ()):
        self.repo, self.pref = repo, device
        local = Path(repo).expanduser()
        self.path = local if local.is_dir() else models_dir() / repo.replace("/", "__")   # your own export works too
        self.vocab = list(dict.fromkeys(list(vocabulary) + VOICE_WORDS))
        self.pipe, self.device, self.errors = None, None, {}
        self._prompt_ok = True
        self.prompt_words = 60
        self.max_tokens = 96

    def ensure(self) -> None:
        if (self.path / "openvino_encoder_model.xml").exists():
            return
        from huggingface_hub import snapshot_download
        print(f"  downloading {self.repo} (one time, ~0.8-1.5 GB)…", flush=True)
        last = None
        for attempt in range(1, 4):
            try:
                snapshot_download(repo_id=self.repo, local_dir=str(self.path))
                return
            except Exception as e:                      # dropped connections are common; resume and retry
                last = e
                print(f"  download interrupted ({type(e).__name__}); retry {attempt}/3…", flush=True)
                time.sleep(3 * attempt)
        raise RuntimeError("could not reach Hugging Face. Check the connection, or set "
                           "$env:HF_ENDPOINT = \"https://hf-mirror.com\" and run: monster models") from last

    def load(self) -> str:
        import openvino_genai as ov_genai
        from . import npu
        order = ["NPU", "GPU", "CPU"] if self.pref == "auto" else [self.pref.upper(), "CPU"]
        avail = npu.devices()
        cache = str(models_dir() / "ov_cache")
        for d in order:
            if d != "CPU" and not any(k.startswith(d) for k in avail):
                continue
            t0 = time.perf_counter()
            self.prompt_words = 60                             # each device gets the full chance
            try:
                try:
                    self.pipe = ov_genai.WhisperPipeline(str(self.path), d, CACHE_DIR=cache)
                except TypeError:
                    self.pipe = ov_genai.WhisperPipeline(str(self.path), d)
                self.device = d
                self._warm()
                self.load_s = round(time.perf_counter() - t0, 1)
                return d
            except Exception as e:
                self.errors[d] = f"{type(e).__name__}: {str(e)[:160]}"
                self.pipe = None
        raise RuntimeError(f"Whisper could not load on any device: {self.errors}")

    def _warm(self) -> None:
        """First inference (compiles on the NPU). The NPU pipeline has a fixed-size
        decoder window, so a long vocabulary prompt can overflow it
        ("roi_end <= max_dim"): shrink the prompt, then drop it, before giving up."""
        last = None
        warm = (np.random.default_rng(0).standard_normal(16000) * 0.003).tolist()   # quiet noise, not digital silence
        for words in (self.prompt_words, 12, 0):
            self.prompt_words = words
            self._prompt_ok = words > 0
            try:
                self._run(warm)
                return
            except Exception as e:
                last = e
        raise last

    def _run(self, samples, prompt: bool = True) -> str:
        # Commands are short. A cap also keeps the NPU's fixed-size decoder cache from
        # overflowing when Whisper hallucinates on silence.
        kwargs = {"max_new_tokens": self.max_tokens}
        if prompt and self._prompt_ok and self.vocab and self.prompt_words:
            kwargs["initial_prompt"] = "Vocabulary: " + ", ".join(self.vocab[:self.prompt_words]) + "."
        try:
            res = self.pipe.generate(samples, **kwargs)
        except TypeError:
            self._prompt_ok = False                           # older GenAI: no initial_prompt
            res = self.pipe.generate(samples, max_new_tokens=self.max_tokens)
        text = res.texts[0] if getattr(res, "texts", None) else str(res)
        return text.strip()

    def transcribe(self, audio, prompt: bool = True) -> str:
        """prompt=False skips the vocabulary hint: used to double-check a wake,
        where a hint like "Lazy Monster" could make Whisper imagine the word in noise."""
        if self.pipe is None or len(audio) < 16000 * 0.3:
            return ""
        return self._run(audio.tolist(), prompt)


_WAKE_LEAD = re.compile(r"^\W*(?:\w+\W+){0,2}?mon\w*\b[\s,.!?]*", re.I)


def strip_wake_lead(text: str) -> str:
    """Whisper may spell the wake phrase differently than Moonshine did."""
    m = _WAKE_LEAD.match(text)
    return text[m.end():].strip() if m else text.strip()


# ---- macOS backends for the accurate pass ----------------------------------------------
class MLXRefiner(WhisperRefiner):
    """Apple Silicon: Whisper through MLX on the GPU (unified memory)."""

    def __init__(self, repo: str = "mlx-community/distil-whisper-large-v3", vocabulary: Iterable[str] = ()):
        super().__init__(repo, "gpu", vocabulary)
        self.mlx = None

    def ensure(self) -> None:
        from huggingface_hub import snapshot_download
        if not (self.path / "config.json").exists() and not any(self.path.glob("*.safetensors")):
            print(f"  downloading {self.repo} (one time)…", flush=True)
            snapshot_download(repo_id=self.repo, local_dir=str(self.path))

    def load(self) -> str:
        import mlx_whisper
        t0 = time.perf_counter()
        self.mlx = mlx_whisper
        self.device = "Apple GPU (MLX)"
        self._warm()
        self.load_s = round(time.perf_counter() - t0, 1)
        return self.device

    def _run(self, samples, prompt: bool = True) -> str:
        audio = np.asarray(samples, dtype=np.float32)
        kw = {"path_or_hf_repo": str(self.path), "language": "en", "condition_on_previous_text": False}
        if prompt and self._prompt_ok and self.vocab and self.prompt_words:
            kw["initial_prompt"] = "Vocabulary: " + ", ".join(self.vocab[:self.prompt_words]) + "."
        return str(self.mlx.transcribe(audio, **kw).get("text", "")).strip()

    def transcribe(self, audio, prompt: bool = True) -> str:
        if self.mlx is None or len(audio) < 16000 * 0.3:
            return ""
        return self._run(audio, prompt)


class FasterWhisperRefiner(WhisperRefiner):
    """Intel Macs (and a fallback anywhere): CTranslate2 int8 on the CPU."""

    def __init__(self, model: str = "small.en", vocabulary: Iterable[str] = ()):
        super().__init__(model, "cpu", vocabulary)
        self.model_name, self.fw = model, None

    def ensure(self) -> None:
        pass                                            # faster-whisper downloads on first load

    def load(self) -> str:
        from faster_whisper import WhisperModel
        t0 = time.perf_counter()
        self.fw = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                               download_root=str(models_dir() / "faster-whisper"))
        self.device = "CPU"
        self._warm()
        self.load_s = round(time.perf_counter() - t0, 1)
        return self.device

    def _run(self, samples, prompt: bool = True) -> str:
        audio = np.asarray(samples, dtype=np.float32)
        kw = {"language": "en", "beam_size": 1, "condition_on_previous_text": False, "vad_filter": False}
        if prompt and self._prompt_ok and self.vocab and self.prompt_words:
            kw["initial_prompt"] = "Vocabulary: " + ", ".join(self.vocab[:self.prompt_words]) + "."
        segs, _ = self.fw.transcribe(audio, **kw)
        return " ".join(s.text.strip() for s in segs).strip()

    def transcribe(self, audio, prompt: bool = True) -> str:
        if self.fw is None or len(audio) < 16000 * 0.3:
            return ""
        return self._run(audio, prompt)


def make_refiner(cfg, vocabulary):
    """The accurate pass for this machine."""
    from .platform_info import IS_APPLE_SILICON, IS_MAC
    if IS_APPLE_SILICON:
        return MLXRefiner(cfg.stt_model_mac_arm, vocabulary)
    if IS_MAC:
        return FasterWhisperRefiner(cfg.stt_model_mac_intel, vocabulary)
    return WhisperRefiner(cfg.stt_model, cfg.stt_device, vocabulary)
