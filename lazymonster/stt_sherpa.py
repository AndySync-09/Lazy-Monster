"""Streaming speech recognition with sherpa-onnx (Zipformer, 20M, int8, CPU).

Used where the Moonshine streaming package isn't available (macOS). Same
contract as the Moonshine mic: partial text while you speak, a completed line at
each pause, mute() while the monster talks. About 8% of one CPU core."""
import queue
import tarfile
import threading
from pathlib import Path

import numpy as np

from .models import download, models_dir

URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
       "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2")
DIRNAME = "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17"


def ensure_model() -> Path:
    base = models_dir() / "sherpa"
    d = base / DIRNAME
    if (d / "tokens.txt").exists():
        return d
    base.mkdir(parents=True, exist_ok=True)
    arc = download(URL, base / (DIRNAME + ".tar.bz2"), "streaming speech model")
    with tarfile.open(arc) as t:
        t.extractall(base)
    arc.unlink(missing_ok=True)
    return d


def recognizer(pause_s: float = 0.6):
    import sherpa_onnx
    d = ensure_model()
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(d / "tokens.txt"), encoder=str(d / "encoder-epoch-99-avg-1.int8.onnx"),
        decoder=str(d / "decoder-epoch-99-avg-1.onnx"), joiner=str(d / "joiner-epoch-99-avg-1.int8.onnx"),
        num_threads=2, enable_endpoint_detection=True, rule1_min_trailing_silence=2.4,
        rule2_min_trailing_silence=pause_s, rule3_min_utterance_length=20, decoding_method="greedy_search")


class SherpaMic:
    """Measured quirk: speech that starts within ~1 s of a fresh or reset stream loses
    its first syllables ("Hey Monster" -> "nster"). So the stream is never restarted
    around your words: while the monster talks it hears silence instead of nothing,
    and when it wakes from sleep it replays the last 2.5 s of real audio first."""

    def __init__(self, on_partial, on_complete, device=None):
        import collections
        self.on_partial, self.on_complete, self.device = on_partial, on_complete, device
        self.rec = recognizer()
        self.stream = self.rec.create_stream()
        self.stream.accept_waveform(16000, np.zeros(16000, dtype=np.float32))
        self.q: "queue.Queue" = queue.Queue(maxsize=400)
        self.ring = collections.deque(maxlen=25)            # last 2.5 s, always kept
        self.mode = "live"                                  # live | silence (speaking) | off (asleep, paused)
        self.line = 0
        self.audio = None
        self._stop = threading.Event()

    # same surface as moonshine's MicTranscriber
    def load(self):
        return self

    def set_keyterms(self, terms):
        pass                                       # Whisper's vocabulary prompt covers names on this path

    def mute(self, on: bool):
        self.set_reasons({"speaking"} if on else set())

    def set_reasons(self, reasons):
        mode = "off" if ({"idle", "paused"} & set(reasons)) else ("silence" if reasons else "live")
        if mode == self.mode:
            return
        waking = self.mode == "off" and mode == "live"
        self.mode = mode
        if waking:                                 # replay what was just said ("Hey Monster, mute")
            self.stream = self.rec.create_stream()
            self._put(np.zeros(40000, dtype=np.float32))   # 2.5 s warm-up so the replay is not clipped
            for b in list(self.ring):
                self._put(b)

    def _put(self, block):
        try:
            self.q.put_nowait(block)
        except queue.Full:
            pass

    def on_audio(self, block: np.ndarray):
        """Microphone callback logic (also used by tests)."""
        self.ring.append(block)
        if self.mode == "live":
            self._put(block)
        elif self.mode == "silence":
            self._put(np.zeros_like(block))

    def start(self):
        import sounddevice as sd
        self.audio = sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=1600,
                                    callback=lambda indata, frames, t, status: self.on_audio(indata[:, 0].copy()),
                                    device=self.device)
        self.audio.start()
        threading.Thread(target=self._loop, daemon=True, name="lazymonster-sherpa").start()
        return self

    def drain(self):
        """Decode everything queued (tests and file benchmarks)."""
        while not self.q.empty():
            self._decode(self.q.get_nowait())

    def _decode(self, block):
        r, s = self.rec, self.stream
        s.accept_waveform(16000, block)
        while r.is_ready(s):
            r.decode_stream(s)
        text = r.get_result(s).strip().lower()
        if text:
            self.on_partial(self.line + 1, text)
        if r.is_endpoint(s) and text:              # never reset on silence: resets clip the next words
            self.line += 1
            self.on_complete(self.line, text)
            r.reset(s)

    def _loop(self):
        while not self._stop.is_set():
            try:
                block = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._decode(block)
            except Exception:
                self.stream = self.rec.create_stream()

    def close(self):
        self._stop.set()
        if self.audio is not None:
            self.audio.stop()
            self.audio.close()
