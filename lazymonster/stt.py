"""Moonshine streaming STT glue (on-device; English models are MIT-licensed)."""
from typing import Callable

# English streaming models published by moonshine-voice 0.1.5: tiny, small, medium.
ARCH = {"tiny": "TINY_STREAMING", "small": "SMALL_STREAMING", "medium": "MEDIUM_STREAMING"}


def model_arch(name: str):
    from moonshine_voice import ModelArch
    return getattr(ModelArch, ARCH.get(name, "SMALL_STREAMING"))


def _lid(line) -> int:
    return int(getattr(line, "line_id", getattr(line, "id", 0)))


def make_listener(on_partial: Callable[[int, str], None], on_complete: Callable[[int, str], None]):
    from moonshine_voice import TranscriptEventListener

    class _L(TranscriptEventListener):
        def on_line_text_changed(self, event):
            if event.line.text:
                on_partial(_lid(event.line), event.line.text)

        def on_line_completed(self, event):
            on_complete(_lid(event.line), event.line.text or "")

    return _L()


def open_mic(model: str, update_interval: float, keyterms, on_partial, on_complete, device=None):
    """Moonshine where its streaming build exists (Windows, Linux); sherpa-onnx elsewhere (macOS)."""
    try:
        from moonshine_voice import MicTranscriber  # noqa: F401
    except Exception:
        from .stt_sherpa import SherpaMic
        return SherpaMic(on_partial, on_complete, device).load()
    from moonshine_voice import MicTranscriber

    def build(arch):
        m = MicTranscriber().language("en").update_interval(update_interval)
        if arch is not None:
            m.model_arch(arch)
        if device is not None:
            m.device(int(device) if str(device).isdigit() else device)
        m.add_listener(make_listener(on_partial, on_complete))
        return m

    try:
        mic = build(model_arch(model)).load()
    except ValueError as e:                       # model not in this package's catalog
        print(f"  model '{model}' unavailable ({str(e)[:80]}…); using the package default")
        mic = build(None).load()
    try:
        mic.set_keyterms(keyterms)
    except Exception as e:
        print(f"  (keyterm biasing unavailable: {e})")
    return mic


class MicGate:
    """One place that decides whether the streaming transcriber hears audio.
    Muted while the monster speaks, while paused, and (with the NPU wake word)
    while idle, so the CPU transcriber only runs after "Hey Monster"."""

    def __init__(self):
        import threading
        self.mic, self.reasons, self._lock = None, set(), threading.Lock()

    def set(self, reason: str, on: bool) -> None:
        with self._lock:
            (self.reasons.add if on else self.reasons.discard)(reason)
            muted = bool(self.reasons)
            reasons = set(self.reasons)
        if self.mic is not None:
            try:
                if hasattr(self.mic, "set_reasons"):
                    self.mic.set_reasons(reasons)        # sherpa: knows *why* it's muted
                else:
                    self.mic.mute(muted)
            except Exception:
                pass

    def has(self, reason: str) -> bool:
        return reason in self.reasons
