"""What the settings panel talks to. Every change is saved and applied live."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from .config import save_setting
from .control import KEY_ENV, MODEL_FIELD, list_models, set_key

VOICES = [("af_heart", "US, warm"), ("af_bella", "US, bright"), ("af_nicole", "US, soft"), ("af_sarah", "US, calm"),
          ("am_adam", "US, deep"), ("am_michael", "US, friendly"), ("bf_emma", "UK, clear"), ("bm_george", "UK, classic"),
          ("hf_alpha", "Indian English"), ("hf_beta", "Indian English, lighter"), ("hm_omega", "Indian English, male")]


class SettingsCtl:
    def __init__(self, cfg, engine, conv, speaker, bus, det_ref, lock_ref, refresh_status):
        self.cfg, self.engine, self.conv, self.speaker, self.bus = cfg, engine, conv, speaker, bus
        self.det_ref, self.lock_ref, self.refresh_status = det_ref, lock_ref, refresh_status

    def get(self) -> dict:
        from . import __version__
        from .secrets import get_key
        c = self.cfg
        return {"planner": c.planner, "go_big": c.go_big, "decider": c.decider,
                "models": {p: getattr(c, f) for p, f in MODEL_FIELD.items()},
                "have": {"openai": bool(get_key(KEY_ENV["openai"])), "anthropic": bool(get_key(KEY_ENV["anthropic"])),
                         "local": bool(c.local_base_url)},
                "local_base_url": c.local_base_url, "brain": self.engine.brain.describe(),
                "voice": c.kokoro_voice, "voices": VOICES, "wake_sensitivity": c.wake_sensitivity,
                "voice_lock": c.voice_lock and self.engine.verify is not None, "voice_lock_ready": self.lock_ref.get("lock") is not None,
                "conversation_mode": self.engine.conversation_mode, "barge_in": self.conv.barge_in,
                "push_to_talk": c.push_to_talk, "version": __version__}

    def models(self, provider: str):
        return list_models(self.cfg, provider)

    def set(self, key: str, value):
        c, e, msg = self.cfg, self.engine, "Saved."
        if key == "planner":
            msg = e.brain.switch(str(value))
        elif key == "go_big":
            msg = e.brain.go_big(bool(value))
        elif key == "model":
            prov, model = value.get("provider", c.planner), value.get("model", "")
            msg = e.brain.set_model(model, prov)
        elif key == "local_base_url":
            c.local_base_url = str(value).strip().rstrip("/")
            save_setting("local_base_url", c.local_base_url)
            if c.planner == "local":
                err = e.brain.reload()
                msg = f"Saved, but it didn't start: {err}" if err else "Local address saved."
            else:
                msg = "Local address saved. Pick Local to use it."
        elif key == "voice":
            c.kokoro_voice = str(value)
            save_setting("kokoro_voice", c.kokoro_voice)
            if getattr(self.speaker, "kokoro", None) is None:
                msg = "Saved. The Kokoro voices didn't load in this session; restart the monster to use it."
            else:
                self.speaker.kokoro.voice = c.kokoro_voice
                threading.Thread(target=self.speaker.say, args=("Okay, this is my voice now.",), daemon=True).start()
                msg = "Voice changed."
        elif key == "wake_sensitivity":
            c.wake_sensitivity = round(float(value), 2)
            save_setting("wake_sensitivity", c.wake_sensitivity)
            d = self.det_ref.get("detector")
            if d is not None:
                d.threshold = min(0.97, max(0.5, d.head.threshold - c.wake_sensitivity))
            msg = "Wake sensitivity updated."
        elif key == "voice_lock":
            lock = self.lock_ref.get("lock")
            on = bool(value) and lock is not None
            e.verify = self.lock_ref.get("verify") if on else None
            c.voice_lock = on
            save_setting("voice_lock", on)
            msg = "Voice lock on." if on else ("Voice lock off." if lock is not None else "Enroll your voice first.")
        elif key == "conversation_mode":
            e.conversation_mode = c.conversation_mode = bool(value)
            e.followup_window = 20.0 if value else 10.0
            save_setting("conversation_mode", bool(value))
        elif key == "barge_in":
            self.conv.barge_in = c.barge_in = bool(value)
            save_setting("barge_in", bool(value))
        elif key == "push_to_talk":
            c.push_to_talk = str(value)
            save_setting("push_to_talk", c.push_to_talk)
            msg = "Saved. The new key works after the monster restarts."
        elif key == "side":
            self.bus.move_to(str(value))
            msg = "Moved."
        elif key == "look":
            c.look = "particles" if value == "particles" else "mascot"
            save_setting("look", c.look)
            msg = "Look changed."
        elif key == "decider":
            c.decider = "jev" if value else ""
            save_setting("decider", c.decider)
            msg = "Saved. Jev joins after the monster restarts."
        self.refresh_status()
        return msg

    def key(self, provider: str, value: str) -> str:
        env = KEY_ENV.get(provider)
        if not env or not value.strip():
            return "Paste a key first."
        set_key(env, value.strip())
        if self.cfg.planner == provider:
            err = self.engine.brain.reload()
            self.refresh_status()
            return f"Key saved, but the brain didn't start: {err}" if err else "Key saved. " + self.engine.brain.describe()
        return "Key saved. Pick this brain to use it."

    def test(self) -> str:
        return self.engine.brain.test()

    def preview(self, voice: str) -> str:
        k = getattr(self.speaker, "kokoro", None)
        if k is None:
            return "Previews need the Kokoro voice."
        old = k.voice
        k.voice = voice

        def run():
            try:
                self.speaker.say("Hi, this is how I sound. Say hey monster whenever you need me.")
            finally:
                k.voice = self.cfg.kokoro_voice                # back to the voice you picked
        threading.Thread(target=run, daemon=True).start()
        return "Playing."

    def retrain(self) -> str:
        exe = Path(sys.executable).with_name("monster.exe" if os.name == "nt" else "monster")
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", "start", "Retrain Lazy-Monster", str(exe), "voice-reset", "--train"])
        else:
            subprocess.Popen(["open", "-a", "Terminal", str(exe)])
        return "A training window opened. Follow it; the monster restarts with your new voice."
