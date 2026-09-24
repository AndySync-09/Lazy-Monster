import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "lazymonster"


@dataclass
class Config:
    model: str = "small"             # tiny | small | medium  (English streaming models)
    update_interval: float = 0.1
    stable_updates: int = 2
    wake_names: list = field(default_factory=lambda: ["monster", "monsters", "monsta", "monstah", "munster", "mobster", "monstor", "lazy monster"])
    require_prefix: bool = True
    always_listen: bool = False
    apps: dict = field(default_factory=dict)
    planner: str = "openai"          # openai | anthropic | local | none  (the agent's brain)
    go_big: bool = False             # hard tasks move to a stronger (pricier) model
    local_base_url: str = ""         # e.g. http://localhost:11434/v1 (Ollama), :8080/v1 (llama.cpp), :8000/v1 (vLLM)
    local_model: str = ""
    local_api_key_env: str = "LOCAL_LLM_API_KEY"   # only if your server needs one
    local_timeout: float = 180.0
    decider: str = ""                # "jev": TypeSafe's Jev makes fast yes/no/choice calls around the brain
    accelerator: str = "auto"        # auto | npu | gpu | cpu  (for on-device models)
    agent_max_steps: int = 16
    escalation_model: str = "gpt-6-astra"   # stronger model after 2 failures or a long task; "" = never
    voice: str = "kokoro"            # kokoro (local) | openai | windows | off
    kokoro_voice: str = "af_heart"   # af_heart, af_bella, af_nicole, bf_emma, hf_alpha, hf_beta, ...
    kokoro_model_path: str = ""      # your own Kokoro-format .onnx (leave empty for the default download)
    kokoro_voices_path: str = ""     # and its voices .bin
    kokoro_speed: float = 1.05
    kokoro_quality: str = "fp32"     # fp32 (best) | fp16 | int8 (smallest)
    stt_refine: bool = True          # re-hear agent requests with Whisper (local)
    stt_model: str = "OpenVINO/distil-whisper-large-v3-int8-ov"
    stt_device: str = "auto"         # auto = NPU, then GPU, then CPU
    stt_model_mac_arm: str = "mlx-community/distil-whisper-large-v3"   # Apple Silicon (MLX)
    stt_model_mac_intel: str = "small.en"                              # Intel Mac (faster-whisper)
    vocabulary: list = field(default_factory=list)   # extra words to recognise (names, places)
    ui: bool = True
    wake_engine: str = "auto"        # auto (NPU model if trained, plus transcript) | transcript
    wake_sensitivity: float = 0.0    # raise (e.g. 0.1) if it misses you; lower if it wakes by itself
    idle_gate: bool = True           # with the NPU wake word, pause the CPU transcriber while idle
    conversation_mode: bool = True   # keep listening ~20 s after every reply ("that's all" ends it)
    barge_in: bool = True            # talk over the monster to interrupt it (needs the voice lock)
    wake_confirm: bool = True        # second opinion before waking: Whisper must hear "monster" (and the voice lock, you)
    turn_delay: float = 0.9          # seconds of quiet that end your turn (a pause mid-sentence is fine)
    chimes: bool = True              # three soft sounds: wake, done, error
    acks: bool = True                # say "On it" when a task starts
    greet: bool = True               # "Hi Andy, how can I help?" after a bare "Hey Monster"
    user_name: str = ""              # empty = first name from your Windows account
    quick_brain: bool = False        # simple one-step requests handled by a small model on the NPU
    quick_brain_model: str = ""      # chosen by: monster bench-brain
    quick_brain_device: str = "NPU"
    skin: str = "classic"            # classic | mint | sunset | midnight | bubblegum
    outfit: str = "auto"             # auto (seasonal) | "" | party | diwali | santa | cricket | shades
    pet_mode: bool = False           # while napping, walk along the taskbar
    send_screenshots: bool = False   # let a cloud brain see screenshots (off: text + on-device OCR only)
    ocr_device: str = "auto"         # auto (NPU, then GPU, then CPU) | NPU | GPU | CPU
    look: str = "mascot"             # mascot (animated character) | particles (the classic particle monster)
    window_x: int = -1               # where you dragged the window (-1 = bottom-left corner)
    window_y: int = -1
    hide_after: float = 0.0          # background mode: hide the orb entirely after this long asleep (0 = keep the orb)
    voice_lock: bool = True          # once enrolled (monster voice-enroll), act only on your voice
    push_to_talk: str = "ctrl+alt+space" if os.name == "nt" else "cmd+shift+space"   # global hotkey; "" = off
    default_save_dir: str = "C:\\temp" if os.name == "nt" else str(Path.home() / "Documents" / "LazyMonster" / "Saved")
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    tts_instructions: str = "Warm, upbeat and a little playful, like a helpful friend. Brisk pace. Short sentences."
    openai_model: str = "gpt-5.4-mini"
    openai_api_key_env: str = "OPENAI_API_KEY"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout: float = 90.0
    openai_reasoning_effort: str = "low"   # dropped automatically if the model doesn't support it
    anthropic_model: str = "claude-haiku-4-5-20251001"
    anthropic_escalation_model: str = "claude-sonnet-5"
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    jev_api_key_env: str = "TYPESAFE_API_KEY"
    jev_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    jev_timeout: float = 2.5
    log_text: bool = True
    beeps: bool = True

    @staticmethod
    def load(path: Optional[str] = None) -> "Config":
        p = Path(path) if path else config_dir() / "config.toml"
        cfg = Config()
        for src in (p, config_dir() / "settings.toml"):        # settings.toml = changes made in the app
            if not src.is_file():
                continue
            with open(src, "rb") as f:
                data = tomllib.load(f)
            for k, v in data.get("lazymonster", data).items():
                if k in ("jev", "openai", "anthropic") and isinstance(v, dict):
                    for jk, jv in v.items():
                        if hasattr(cfg, f"{k}_{jk}"):
                            setattr(cfg, f"{k}_{jk}", jv)
                elif hasattr(cfg, k):
                    setattr(cfg, k, v)
        cfg.planner = os.environ.get("LAZYMONSTER_PLANNER", cfg.planner)
        cfg.openai_model = os.environ.get("LAZYMONSTER_OPENAI_MODEL", cfg.openai_model)
        return cfg


def save_setting(key: str, value) -> None:
    """Persist one setting changed from the app (tray/UI) to settings.toml."""
    p = config_dir() / "settings.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if p.is_file():
        with open(p, "rb") as f:
            data = tomllib.load(f).get("lazymonster", {})
    data[key] = value

    def fmt(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, list):
            return "[" + ", ".join(fmt(x) for x in v) + "]"
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    lines = ["# Written by Lazy-Monster when you change settings in the app.", "[lazymonster]"]
    lines += [f"{k} = {fmt(v)}" for k, v in sorted(data.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
