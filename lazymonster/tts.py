"""The monster's voice. Backends: Kokoro-82M (local, open source, default),
OpenAI TTS (cloud), Windows SAPI (instant fallback), or off. Speaking blocks the caller so the
follow-up listening window starts after the monster stops talking, and the
microphone is muted meanwhile so it never hears itself."""
import os
import re
import threading
import time
from typing import Callable, Optional


def _clean(text: str) -> str:
    text = re.sub(r"[`*_#>]+", "", text)                 # no markdown read aloud
    def _speakable(m):                                     # C:\\temp\\haiku.txt -> "haiku.txt in temp"
        raw = m.group(0)
        tail = "." if raw.endswith(".") else ""
        parts = [x for x in raw.rstrip(".").split("\\") if x]
        return parts[-1] + (f" in {parts[-2]}" if len(parts) > 2 else "") + tail
    text = re.sub(r"[A-Za-z]:\\[^\s;,]+", _speakable, text)
    return re.sub(r"\s+", " ", text).strip()[:600]


KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_FILES = {"fp32": "kokoro-v1.0.onnx", "fp16": "kokoro-v1.0.fp16.onnx", "int8": "kokoro-v1.0.int8.onnx"}


class KokoroVoice:
    """Kokoro-82M (Apache 2.0) via ONNX Runtime. Speaks sentence by sentence:
    the next sentence renders while the current one plays."""

    def __init__(self, voice: str = "af_heart", speed: float = 1.05, quality: str = "fp32"):
        self.voice, self.speed, self.quality = voice, speed, quality
        self.k = None
        self.cancel = threading.Event()

    def ensure(self):
        from .models import download, models_dir
        d = models_dir() / "kokoro"
        d.mkdir(exist_ok=True)
        name = KOKORO_FILES.get(self.quality, KOKORO_FILES["fp32"])
        m = download(KOKORO_URL + name, d / name, "Kokoro voice model")
        v = download(KOKORO_URL + "voices-v1.0.bin", d / "voices-v1.0.bin", "Kokoro voices")
        return m, v

    def load(self):
        if self.k is None:
            from kokoro_onnx import Kokoro
            m, v = self.ensure()
            self.k = Kokoro(str(m), str(v))
        return self

    def speak(self, text: str) -> None:
        import queue
        import sounddevice as sd
        from .textops import sentences
        self.load()
        q: "queue.Queue" = queue.Queue(maxsize=2)

        def produce():
            for s in sentences(text):
                if self.cancel.is_set():
                    break
                audio, sr = self.k.create(s, voice=self.voice, speed=self.speed, lang="en-us")
                q.put((audio, sr))
            q.put(None)

        threading.Thread(target=produce, daemon=True).start()
        while True:
            item = q.get()
            if item is None or self.cancel.is_set():
                break
            sd.play(item[0], samplerate=item[1])
            while sd.get_stream().active:               # poll so an interrupt stops mid-sentence
                if self.cancel.is_set():
                    sd.stop()
                    break
                time.sleep(0.03)


class Speaker:
    def __init__(self, backend: str = "kokoro", model: str = "gpt-4o-mini-tts", voice: str = "coral",
                 instructions: str = "", api_key_env: str = "OPENAI_API_KEY",
                 base_url: str = "https://api.openai.com/v1", timeout: float = 20.0):
        self.backend = backend.lower()
        self.model, self.voice, self.instructions = model, voice, instructions
        self.key, self.base_url, self.timeout = os.environ.get(api_key_env, ""), base_url.rstrip("/"), timeout
        self.on_start: Callable[[], None] = lambda: None
        self.on_end: Callable[[], None] = lambda: None
        self._lock = threading.Lock()
        self._sapi = None
        self.kokoro = None
        self.speaking = False

    def say(self, text: str) -> None:
        text = _clean(text)
        if not text or self.backend == "off":
            return
        with self._lock:
            self.speaking = True
            if self.kokoro is not None:
                self.kokoro.cancel.clear()
            self.on_start()
            try:
                if self.backend == "kokoro" and self.kokoro is not None:
                    try:
                        self.kokoro.speak(text)
                        return
                    except Exception as e:
                        print(f"  (voice: Kokoro failed, using Windows voice: {str(e)[:80]})", flush=True)
                if self.backend == "openai" and self.key:
                    try:
                        self._openai(text)
                        return
                    except Exception as e:
                        print(f"  (voice: OpenAI TTS failed, using Windows voice: {str(e)[:80]})", flush=True)
                self._windows(text)
            except Exception as e:
                print(f"  (voice unavailable: {str(e)[:80]})", flush=True)
            finally:
                self.speaking = False
                self.on_end()

    def interrupt(self) -> None:
        """Barge-in: stop talking now (Kokoro and OpenAI voices)."""
        if self.kokoro is not None:
            self.kokoro.cancel.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def _openai(self, text: str) -> None:
        import numpy as np
        import requests
        import sounddevice as sd
        body = {"model": self.model, "voice": self.voice, "input": text, "response_format": "pcm"}
        if self.instructions:
            body["instructions"] = self.instructions
        r = requests.post(f"{self.base_url}/audio/speech", json=body, timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        audio = np.frombuffer(r.content, dtype=np.int16)      # 24 kHz mono 16-bit PCM
        sd.play(audio, samplerate=24000)
        sd.wait()

    def _windows(self, text: str) -> None:
        if os.name != "nt":
            return
        if self._sapi is None:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
            import win32com.client
            self._sapi = win32com.client.Dispatch("SAPI.SpVoice")
        self._sapi.Speak(text, 0)                             # synchronous


def build_speaker(cfg, load: bool = True) -> Speaker:
    s = Speaker(cfg.voice, cfg.tts_model, cfg.tts_voice, cfg.tts_instructions,
                cfg.openai_api_key_env, cfg.openai_base_url)
    if cfg.voice == "kokoro":
        s.kokoro = KokoroVoice(cfg.kokoro_voice, cfg.kokoro_speed, cfg.kokoro_quality)
        if load:
            try:
                s.kokoro.load()
            except Exception as e:
                print(f"  (Kokoro unavailable, using Windows voice: {str(e)[:100]})", flush=True)
                s.kokoro = None
    return s
