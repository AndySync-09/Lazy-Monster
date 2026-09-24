"""The quick brain: a small language model on the Intel NPU for simple, one-step requests.

"Open Spotify", "volume 30", "remind me at 5 to call Priya", "write a haiku in Notepad":
the NPU model answers with one line of JSON naming a tool, and the monster does it without
the cloud. Anything bigger, or anything it isn't sure about, it hands off to the main brain
(GPT, Claude or a local model). Nothing it does skips the usual safety checks."""
import json
import re
import time
from pathlib import Path
from typing import Optional, Tuple

QUICK_TOOLS = {
    "open_app": "app", "close_app": "app", "search_web": "query", "open_url": "url", "volume_set": "level",
    "mute": "", "unmute": "", "media_play_pause": "", "media_next": "", "new_tab": "",
    "write_in_app": "app, text", "set_reminder": "what, when", "list_reminders": "", "system_status": "",
}

# Short on purpose: on the NPU most of the time goes into reading the prompt, so every word costs.
SYSTEM = ('Voice assistant router. Reply with one line of JSON: {"tool": name, "args": {...}}. '
          'Use {"tool": "hand_off"} for anything with several steps, research, code, documents, files, email, '
          "the screen, or if unsure.\nTools: " + "; ".join(f"{n}({a})" for n, a in QUICK_TOOLS.items()) + "\n"
          'play music -> {"tool": "media_play_pause", "args": {}}\n'
          'open spotify -> {"tool": "open_app", "args": {"app": "Spotify"}}\n'
          'remind me at 5 to call priya -> {"tool": "set_reminder", "args": {"what": "call Priya", "when": "at 5 pm"}}\n'
          'write a haiku about rain in notepad -> {"tool": "write_in_app", "args": {"app": "Notepad", "text": "Soft rain on the roof\\nthe city exhales slowly\\npuddles hold the sky"}}\n'
          'build a snake game -> {"tool": "hand_off"}')

SAY = {"open_app": "Opening {app}.", "close_app": "Closing {app}.", "search_web": "Searching for {query}.",
       "open_url": "Opening it.", "volume_set": "Volume at {level}.", "mute": "Muted.", "unmute": "Sound's back.",
       "media_play_pause": "Okay.", "media_next": "Next one.", "new_tab": "New tab.", "write_in_app": "Done, it's in {app}."}

_BIG = __import__("re").compile(r"\b(and then|then|research|build|create|code|script|program|slides?|presentation|deck|"
                                r"document|report|email|mail|file|folder|screen|summari[sz]e|explain|compare|website|"
                                r"project|install|run it|fix|debug)\b", __import__("re").I)


def looks_simple(task: str) -> bool:
    """Only short, one-thing requests go to the quick brain, so bigger ones don't wait for it."""
    return len(task.split()) <= 14 and not _BIG.search(task)


CANDIDATES = ["llmware/qwen2.5-1.5b-instruct-ov", "OpenVINO/Qwen2.5-1.5B-Instruct-int4-ov",
              "llmware/Qwen2.5-VL-3B-Instruct-ov-int4-npu"]

TESTS = [("open spotify", "open_app"), ("set the volume to 40", "volume_set"), ("mute", "mute"),
         ("play some music", "media_play_pause"), ("search the web for bangalore weather", "search_web"),
         ("remind me in 20 minutes to stretch", "set_reminder"), ("why is my laptop slow", "system_status"),
         ("write a haiku about coffee in notepad", "write_in_app"), ("open github.com", "open_url"),
         ("build a snake game in python and run it", "hand_off"),
         ("research the latest nvidia news and make three slides", "hand_off"),
         ("what are my reminders", "list_reminders")]


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"tool": "hand_off"}
    raw = m.group(0)
    for cand in (raw, raw.replace("'", '"')):
        try:
            d = json.loads(cand)
            return d if isinstance(d, dict) else {"tool": "hand_off"}
        except ValueError:
            continue
    return {"tool": "hand_off"}


class QuickBrain:
    def __init__(self, model_dir: Path, device: str = "NPU", cache_dir: Optional[Path] = None):
        import openvino_genai as ovg
        cfg = {"CACHE_DIR": str(cache_dir)} if cache_dir else {}
        if device == "NPU":
            cfg.update({"MAX_PROMPT_LEN": 1536, "MIN_RESPONSE_LEN": 128})
        t0 = time.perf_counter()
        self.vlm = (Path(model_dir) / "openvino_vision_embeddings_model.xml").exists()
        kind = ovg.VLMPipeline if self.vlm else ovg.LLMPipeline
        try:
            self.pipe = kind(str(model_dir), device, **cfg)
        except Exception:
            cfg.pop("MAX_PROMPT_LEN", None)                  # not every pipeline takes the NPU prompt-size hints
            cfg.pop("MIN_RESPONSE_LEN", None)
            self.pipe = kind(str(model_dir), device, **cfg)
        self.load_s = time.perf_counter() - t0
        self.device = device
        self.gen = ovg.GenerationConfig()
        self.gen.max_new_tokens = 72
        self.gen.do_sample = False

    def ask(self, request: str) -> Tuple[dict, float]:
        t0 = time.perf_counter()
        self.pipe.start_chat(SYSTEM)
        try:
            out = self.pipe.generate(request, generation_config=self.gen)
        finally:
            self.pipe.finish_chat()
        text = out.texts[0] if hasattr(out, "texts") else str(out)
        return parse(text), time.perf_counter() - t0

    def handle(self, request: str):
        """(intent, words to say, seconds) for a simple request, or None to hand it to the main brain."""
        from .intents import validate
        d, secs = self.ask(request)
        name = d.get("tool")
        if name not in QUICK_TOOLS:
            return None
        try:
            intent = validate(name, d.get("args") or {}, source="agent", allow_refs=False)
        except Exception:
            return None
        try:
            say = SAY.get(name, "Done.").format(**intent.args)
        except (KeyError, IndexError):
            say = "Done."
        return intent, say, secs


def model_path(repo: str) -> Path:
    from .models import models_dir
    return models_dir() / repo.replace("/", "__")


def download(repo: str, say=print) -> bool:
    from huggingface_hub import snapshot_download
    for attempt in range(1, 5):
        try:
            snapshot_download(repo, local_dir=str(model_path(repo)), max_workers=2)
            return True
        except Exception as e:
            say(f"  download attempt {attempt} failed ({type(e).__name__}: {str(e).splitlines()[0][:90]})")
            time.sleep(3 * attempt)
    return False


_quick = None


def load(cfg) -> Optional[QuickBrain]:
    """The quick brain from settings, or None (off, not downloaded, or the NPU refused it)."""
    global _quick
    if _quick is None and cfg.quick_brain and cfg.quick_brain_model:
        p = model_path(cfg.quick_brain_model)
        if p.exists():
            from .models import models_dir
            try:
                _quick = QuickBrain(p, cfg.quick_brain_device, models_dir() / "ov_cache")
            except Exception:
                _quick = None
    return _quick
