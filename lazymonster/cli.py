import argparse
import os
import csv
import json
import statistics
import sys
import time
from pathlib import Path

from . import __version__
from .actions import make_executor
from .apps import AppIndex
from .config import Config, config_dir
from .engine import Engine
from .agent import Agent, AgentError, build_client
from .worker import Worker
from .feedback import make_feedback
from .grammar import Grammar
from .intents import Intent
from .wake import WakeSpotter


def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def require_venv() -> None:
    if in_venv() or os.environ.get("LAZYMONSTER_ALLOW_GLOBAL") == "1":
        return
    print("Lazy-Monster must run inside its virtual environment.\n"
          "From the lazy-monster folder run:  powershell -ExecutionPolicy Bypass -File .\\setup.ps1\n"
          "then:                          .\\.venv\\Scripts\\monster.exe run --dry-run -v", file=sys.stderr)
    sys.exit(2)


def _build(cfg: Config, dry_run: bool, logger=None, feedback=None, clock=time.monotonic,
           synchronous=False, use_agent=True, on_exit=None, speaker=None, on_say=None):
    aliases = None
    if cfg.apps:
        from .apps import DEFAULT_ALIASES
        aliases = {**DEFAULT_ALIASES, **cfg.apps}
    apps = AppIndex(aliases)
    grammar = Grammar(apps.resolve)
    executor = make_executor(apps, dry_run)
    executor.default_save_dir = cfg.default_save_dir

    def log(**kw):
        if logger:
            logger(json.dumps(kw, default=str))

    def say(t):
        print(f"  monster: {t}", flush=True)
        if on_say is not None:
            on_say(t)
        if speaker is not None:
            speaker.say(t)
    worker = Worker(executor, log, synchronous=synchronous, clock=clock)
    if use_agent and cfg.planner != "none":
        try:
            client = build_client(cfg)
            if client is not None:
                worker.agent = Agent(client, executor, log, say, max_steps=cfg.agent_max_steps, clock=clock)
                worker.agent.journal = True
                if cfg.escalation_model and cfg.planner == "openai" and cfg.escalation_model != cfg.openai_model:
                    from .agent import ChatClient
                    worker.agent.escalation = ChatClient(cfg.escalation_model, cfg.openai_api_key_env, cfg.openai_base_url,
                                                         cfg.openai_timeout, cfg.openai_reasoning_effort)
        except AgentError as e:
            print(f"  agent off: {e}", file=sys.stderr)
    engine = Engine(grammar, WakeSpotter(cfg.wake_names, require_prefix=cfg.require_prefix),
                    worker, agent_enabled=worker.agent is not None, feedback=feedback,
                    stable_updates=cfg.stable_updates, always_listen=cfg.always_listen,
                    logger=logger, clock=clock, say=say, on_exit=on_exit)
    if worker.agent is not None:
        worker.agent.on_sleep = engine.go_to_sleep
    return apps, grammar, engine


def _file_logger(cfg: Config):
    d = config_dir(); d.mkdir(parents=True, exist_ok=True)
    path = d / "log.jsonl"

    def log(line: str):
        ev = json.loads(line)
        if not cfg.log_text:
            ev.pop("text", None)
        ev["ts"] = time.time()
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
        e = ev.get("event")
        if e == "dispatched":
            tag = "early" if ev.get("early") else "end-of-line"
            print(f"  → {ev['intent']} {ev.get('args', {})} [{ev['source']}, {tag}, "
                  f"{ev['ms_from_line_start']} ms from speech start]", flush=True)
        elif e == "step":
            print(f"    {'ok  ' if ev['ok'] else 'FAIL'} {ev['n']:>2}. {ev['intent']} {ev['msg']} ({ev['exec_ms']} ms)", flush=True)
        elif e == "task":
            print(f"  task: {ev.get('text', '')}", flush=True)
        elif e == "asking":
            print("  · waiting for your answer…", flush=True)
        elif e == "heard_during_task":
            print(f"  (passed to the running task: {ev.get('text', '')})", flush=True)
        elif e == "agent_done":
            fa = ev.get("first_action_s")
            print(f"  finished in {ev['steps']} steps, {ev['s']} s" + (f" (first action after {fa} s)" if fa is not None else ""), flush=True)
        elif e == "escalated":
            print(f"  handing this one to {ev.get('model')} (harder task)", flush=True)
        elif e in ("task_error", "unknown"):
            print(f"  ! {e}: {ev.get('error', ev.get('text', ''))}", flush=True)
    return log


def _compose(*fns):
    fns = [f for f in fns if f]
    return lambda *args: [f(*args) for f in fns]


def _start_voice(cfg, a, engine, apps, speaker, conv, on_partial=None, on_level=None, status=print):
    """Pass 1: Moonshine streaming (wake + instant commands). Pass 2: Whisper on the
    NPU re-hears each finished request before the agent acts on it."""
    import threading
    from .stt import MicGate, open_mic
    from .stt_refine import VOICE_WORDS, AudioTap
    info = {"stt": "Moonshine only", "wake": "wake: transcript"}
    gate = conv.gate
    tap = AudioTap(device=getattr(a, "device", None)).start()
    conv.tap = tap                                     # its own voice is cut out of what Whisper hears
    det_ref = {}
    if cfg.stt_refine:
        try:
            from .stt_refine import make_refiner
            status("loading accurate speech model (first run downloads it once)…")
            r = make_refiner(cfg, list(cfg.vocabulary) + apps.keyterms(40))
            r.ensure()
            dev = r.load()
            engine.refine = lambda t0: r.transcribe(tap.slice(t0))
            if r.errors:
                why = "; ".join(f"{k}: {v.splitlines()[0][:70]}" for k, v in r.errors.items())
                status(f"(Whisper fell back from {', '.join(r.errors)}: {why})")
            info["stt"] = f"Whisper on {dev}"
            status(f"accurate speech: {r.repo.split('/')[-1]} on {dev} (ready in {r.load_s} s)")
        except Exception as e:
            status(f"accurate speech pass off ({type(e).__name__}: {str(e)[:120]}); using Moonshine only")
    keyterms = list(dict.fromkeys(apps.keyterms() + list(cfg.vocabulary) + VOICE_WORDS))[:150]

    def comp(lid, t):
        if getattr(a, "verbose", False):
            print(f"  heard: {t}", flush=True)
        engine.on_complete(lid, t)

    def part(lid, t):
        engine.on_partial(lid, t)
        if on_partial:
            on_partial(lid, t)

    mic = open_mic(cfg.model, cfg.update_interval, keyterms, part, comp, device=getattr(a, "device", None))
    gate.mic = mic
    mic.start()
    info["lock"] = "voice lock off"
    if cfg.voice_lock:
        try:
            from .voicelock import load_lock
            lock = load_lock()
            if lock is None:
                status("voice lock: not enrolled (monster voice-enroll) - anyone can command it")
            else:
                engine.verify = lambda t0: lock.check(tap.slice(t0))[0]
                info["lock"] = "voice lock on"
                status("voice lock: on (only your voice; typed requests and push-to-talk always work)")
        except Exception as e:
            status(f"voice lock off ({type(e).__name__}: {str(e)[:100]})")
    if cfg.push_to_talk:
        from . import hotkey
        try:
            if hotkey.start(cfg.push_to_talk, conv.push_to_talk):
                info["ptt"] = cfg.push_to_talk
                status(f"push-to-talk: {cfg.push_to_talk}")
            else:
                status(f"push-to-talk: {cfg.push_to_talk} is taken by another app; set push_to_talk in settings")
        except ValueError as e:
            status(f"push-to-talk off ({e})")
    if cfg.wake_engine != "transcript":
        try:
            from .wakeword import load_detector
            det = load_detector(conv.on_wake, cfg.accelerator if cfg.accelerator != "auto" else "auto",
                                cfg.wake_sensitivity)
            if det is None:
                status("wake word: transcript only (train the NPU wake word with: monster wake-train)")
            else:
                tap.listeners.append(det.feed)
                det_ref["detector"] = det
                info["wake"] = f"wake word on {det.stream.f.device}"
                status(f"wake word: Hey Monster model on {det.stream.f.device}")
                conv.wake_model = bool(cfg.idle_gate)   # CPU transcriber sleeps until the NPU hears the wake word
                conv._apply_gate()
        except Exception as e:
            status(f"wake word model off ({type(e).__name__}: {str(e)[:100]})")
    if on_level is not None:

        def levels():
            import numpy as np
            while tap.stream is not None:
                x = tap.slice(time.monotonic() - 0.12, preroll=0)
                on_level(float(np.sqrt(np.mean(x * x))) if len(x) else 0.0)
                time.sleep(0.1)
        threading.Thread(target=levels, daemon=True).start()
    return mic, tap, info, gate, det_ref


class _Relay:
    """Engine hooks exist before the conversation object; forward to it once it does."""

    def __init__(self):
        self.conv = None

    def feedback(self, kind):
        if self.conv:
            self.conv.feedback(kind)

    def log(self, line):
        if self.conv:
            self.conv.log(json.loads(line))


def _conversation(cfg, engine, speaker, stop, emit=lambda ev: None):
    from .conversation import Conversation
    from .stt import MicGate
    from .userinfo import windows_first_name
    conv = Conversation(engine, speaker, MicGate(), emit=emit, chimes=cfg.chimes, speak_acks=cfg.acks,
                        user_name=windows_first_name(cfg.user_name), greet=cfg.greet)
    engine.turn_delay = cfg.turn_delay
    engine.followup_only_on_question = True
    engine.followup_window = 10.0
    conv.recap = True
    if engine.worker.agent is not None:
        engine.worker.agent.on_progress = conv.progress
    conv.run_ticker(stop)
    return conv


def cmd_run(a, cfg):
    cfg.model = a.model or cfg.model
    cfg.always_listen = a.always or cfg.always_listen
    import threading
    from .tts import build_speaker
    stop = threading.Event()
    if a.quiet:
        cfg.voice = "off"
    speaker = build_speaker(cfg)
    relay = _Relay()
    apps, _, engine = _build(cfg, a.dry_run, _compose(_file_logger(cfg), relay.log),
                             _compose(relay.feedback, make_feedback(cfg.beeps)), on_exit=stop.set, speaker=speaker)
    relay.conv = conv = _conversation(cfg, engine, speaker, stop)
    print(f"Lazy-Monster {__version__} · {len(apps.apps)} apps · agent="
          f"{cfg.openai_model if engine.agent_enabled and cfg.planner == 'openai' else cfg.planner if engine.agent_enabled else 'off'}"
          f" · voice={cfg.voice} · {'DRY RUN' if a.dry_run else 'LIVE'}")
    mic, tap, _, _, _ = _start_voice(cfg, a, engine, apps, speaker, conv, status=lambda m: print("  " + m, flush=True))
    print("Say “Hey Monster, …”   Say “Hey Monster, sleep” to exit.")
    try:
        while not stop.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        mic.close()
        if tap:
            tap.close()


def _background_io():
    """monsterw.exe has no console: send output to a log file instead of nowhere."""
    from .config import config_dir
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    log = d / "monster.log"
    # BOM on a new file so PowerShell shows the symbols correctly
    f = open(log, "a", encoding="utf-8-sig" if not log.exists() or log.stat().st_size == 0 else "utf-8", buffering=1)
    sys.stdout = sys.stderr = f
    print(f"\n--- Lazy-Monster {__version__} background start {time.strftime('%Y-%m-%d %H:%M:%S')} ---")


def cmd_ui(a, cfg):
    import threading
    background = getattr(a, "background", False)
    if background:
        from .service import single_instance
        if not single_instance():
            return 0                                   # already running for this user
        _background_io()
    from .tts import build_speaker
    from .ui.app import Api, UIBus, run_window
    stop = threading.Event()
    bus = UIBus()
    if a.quiet:
        cfg.voice = "off"
    speaker = build_speaker(cfg)
    relay = _Relay()
    apps, _, engine = _build(cfg, a.dry_run, _compose(_file_logger(cfg), relay.log, bus.log),
                             _compose(relay.feedback, make_feedback(cfg.beeps), bus.feedback), on_exit=stop.set,
                             speaker=speaker, on_say=bus.say)
    relay.conv = conv = _conversation(cfg, engine, speaker, stop, emit=bus.emit)
    bus.agent = engine.worker.agent
    api = Api(engine, stop, bus, speaker, conv)
    held = {}

    def on_partial(lid, t):
        ln = engine.lines.get(lid)
        if ln and (ln.woke or ln.armed):
            bus.emit({"type": "heard", "text": t, "final": False})

    def backend():
        status = lambda m: (print("  " + m, flush=True), bus.emit({"type": "state", "state": "sleep", "sub": m[:80]}))
        mic, tap, info, gate, det_ref = _start_voice(cfg, a, engine, apps, speaker, conv, on_partial=on_partial,
                                                     on_level=lambda v: bus.emit({"type": "level", "v": round(v, 4)}),
                                                     status=status)
        held.update(mic=mic, tap=tap)
        try:
            if sys.platform == "darwin":
                raise RuntimeError("the macOS menu-bar icon needs the main thread, which the window uses; "
                                   "use the window, the hotkey, or 'monster service stop'")
            from .ui.tray import Tray
            held["tray"] = Tray(bus, speaker, gate, det_ref, stop, conv=conv, engine=engine).start()
        except Exception as e:
            print(f"  tray icon off ({type(e).__name__}: {str(e)[:80]})")
        agent = cfg.openai_model if engine.agent_enabled and cfg.planner == "openai" else ("agent off" if not engine.agent_enabled else cfg.planner)
        voice = {"kokoro": f"Kokoro {cfg.kokoro_voice}", "openai": "OpenAI voice", "windows": "Windows voice"}.get(cfg.voice, "silent")
        bus.emit({"type": "chips", "items": [info["wake"], info["lock"], info["stt"], voice, agent]
                  + ([f"talk: {info['ptt']}"] if info.get("ptt") else []) + (["DRY RUN"] if a.dry_run else [])})
        conv.set("sleeping", 'say "Hey Monster" or type below')

    # "Hey Monster, sleep" shrinks to a small sleeping orb and keeps listening, in every UI mode.
    # "Hey Monster", the hotkey or a click on the orb brings the full window back. Quit is in the tray.
    from . import conversation as C
    engine.exit_message = "Okay. I'll be right here, just say Hey Monster."
    engine.on_exit = lambda: conv.set(C.SLEEPING)
    orb_state = {"on": False, "t": 0}

    def orb_on_state(state):
        if state == C.SLEEPING:
            stamp = orb_state["t"] = time.monotonic()

            def later():
                if conv.state == C.SLEEPING and orb_state["t"] == stamp:
                    bus.set_orb(True)
            t = threading.Timer(2.5, later)                 # let the check mark finish first
            t.daemon = True
            t.start()
        else:
            orb_state["t"] = time.monotonic()
            bus.set_orb(False)
    conv.listeners.append(orb_on_state)
    if background:
        seen = {"asleep_since": time.monotonic()}

        def on_state(state):
            if state == C.SLEEPING:
                seen["asleep_since"] = time.monotonic()
            elif bus.window is not None:
                try:
                    bus.window.show()
                except Exception:
                    pass
        conv.listeners.append(on_state)

        if cfg.hide_after > 0:                              # optional: hide even the orb after a while
            def auto_hide():
                while not stop.is_set():
                    time.sleep(2)
                    if conv.state == C.SLEEPING and time.monotonic() - seen["asleep_since"] > cfg.hide_after:
                        try:
                            bus.window.hide()
                        except Exception:
                            pass
                        seen["asleep_since"] = float("inf")
            threading.Thread(target=auto_hide, daemon=True).start()
    print(f"Lazy-Monster {__version__} · UI · {'DRY RUN' if a.dry_run else 'LIVE'}" + (" · background" if background else ""))
    try:
        run_window(bus, api, backend, stop, hidden=background)
    finally:
        stop.set()
        if held.get("mic"):
            held["mic"].close()
        if held.get("tap"):
            held["tap"].close()
        if held.get("tray"):
            held["tray"].close()


def cmd_wake_train(a, cfg):
    """Train the personal "Hey Monster" detector (runs on the NPU at startup)."""
    from .tts import KokoroVoice
    from .wake_train import build, fit, record_clips
    from .wakeword import Features, model_path
    print("Training your Hey Monster wake word. Everything stays on this PC.")
    kv = KokoroVoice(cfg.kokoro_voice, cfg.kokoro_speed, cfg.kokoro_quality).load()
    feats = Features("CPU")                           # training batch runs on CPU; detection runs on the NPU
    user_pos, user_neg = [], []
    if not a.no_record:
        print(f"\nStep 1/2: say 'Hey Monster' {a.samples} times, the way you normally would.")
        user_pos = record_clips(a.samples, 2.0, "say: Hey Monster")
        print("\nStep 2/2: a few seconds of normal talk and room noise (so it learns what NOT to wake on).")
        user_neg = record_clips(3, 6.0, "talk normally for six seconds (anything except the wake phrase)")
        user_neg += record_clips(1, 5.0, "stay quiet for five seconds")
    print("\nBuilding the training set (a few minutes)…")
    pos, neg = build(kv.k, feats, user_pos, user_neg)
    head, report = fit(pos, neg)
    head.save(model_path(), **report)
    print(f"\nSaved {model_path()}")
    print(f"  held-out recall {report['recall']:.0%}, false-wake rate per window {report['false_positive_rate']:.2%}, "
          f"threshold {report['threshold']}")
    print("Restart monster to use it. If it misses you, set wake_sensitivity = 0.1 in settings; "
          "if it wakes by itself, set -0.1.")
    return 0


def cmd_wake_test(a, cfg):
    """Live wake-word meter: say "Hey Monster" a few times and watch the score."""
    from .stt_refine import AudioTap
    from .wakeword import load_detector
    hits = []
    det = load_detector(lambda s: hits.append(s), cfg.accelerator if cfg.accelerator != "auto" else "auto",
                        cfg.wake_sensitivity)
    if det is None:
        print("no wake model yet: run monster wake-train"); return 1
    f = det.stream.f
    print(f"features: embedding on {f.emb_device}, front end on {f.mel_device}"
          + (f", agreement with CPU {f.agreement:.4f}" if hasattr(f, "agreement") else "")
          + (f" (fell back: {f.errors})" if f.errors else ""))
    print(f"threshold {det.threshold:.2f}. Say 'Hey Monster' a few times for {a.seconds} s…")
    tap = AudioTap(device=getattr(a, "device", None)).start()
    tap.listeners.append(det.feed)
    t_end = time.time() + a.seconds
    try:
        while time.time() < t_end:
            s = det.last_score
            print(f"\r  score {s:4.2f} |{'#' * int(s * 40):<40}| peak {det.peak:4.2f}  wakes {len(hits)}", end="", flush=True)
            time.sleep(0.08)
    finally:
        tap.close()
    print(f"\n  peak score {det.peak:.2f}, wakes {len(hits)}")
    if not hits and det.peak < det.threshold:
        print("  Missed you: set wake_sensitivity to about "
              f"{max(0.05, round(det.threshold - det.peak + 0.05, 2))} (tray > Open settings), or re-run monster wake-train.")
    return 0


def cmd_service(a, cfg):
    from . import service
    if os.name != "nt" and sys.platform != "darwin":
        print("background start is Windows and macOS only for now"); return 1
    if a.action == "install":
        cmd = service.install()
        print(f"  starts at sign-in: {cmd}")
        n = service.stop()                              # exactly one copy: replace any running ones
        if n:
            print(f"  stopped {n} old running copy(ies)")
            time.sleep(1.5)
        service.start()
        print("  started now in the background. Say \"Hey Monster\".")
    elif a.action == "uninstall":
        n = service.stop()
        print(f"  removed from sign-in{'' if service.uninstall() else ' (was not installed)'}; stopped {n} running copy(ies)")
    elif a.action == "start":
        if service.running():
            print("  already running")
        else:
            service.start(); print("  started in the background")
    elif a.action == "stop":
        print(f"  stopped {service.stop()} running copy(ies)")
    else:
        from .userinfo import windows_first_name
        print(f"  at sign-in: {service.installed() or 'not installed'}")
        print(f"  running: {len(service.running())} · greeting name: {windows_first_name(cfg.user_name) or '(none)'}")
        from .config import config_dir
        print(f"  log: {config_dir() / 'monster.log'}")
    return 0


def cmd_voice_enroll(a, cfg):
    """Record your voiceprint so the monster only acts on you."""
    from .voicelock import ENROLL_SENTENCES, VoiceLock
    from .wake_train import record_clips
    print("Voice lock: read each sentence aloud in your normal voice. Everything stays on this PC.")
    v = VoiceLock()
    clips = []
    for s in ENROLL_SENTENCES:
        clips += record_clips(1, 5.0, f'read: "{s}"')
    rep = v.enroll(clips)
    p = v.save()
    print(f"\nSaved {p}\n  your consistency {rep['self_mean']:.2f} (min {rep['self_min']:.2f}), threshold {rep['threshold']:.2f}")
    print("Test it with: monster voice-test   (then ask someone else to try, or play a video)")
    return 0


def cmd_voice_test(a, cfg):
    from .voicelock import load_lock
    from .wake_train import record_clips
    lock = load_lock()
    if lock is None:
        print("not enrolled yet: run monster voice-enroll"); return 1
    for i in range(a.times):
        clip = record_clips(1, 4.0, "say anything (or let someone else speak)")[0]
        ok, score = lock.check(clip)
        print(f"  {'YOU' if ok else 'not you'}  similarity {score:.2f} (threshold {lock.threshold:.2f})")
    return 0


INSTALL_URL = "https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.ps1"


def cmd_update(a, cfg):
    """Re-run the one-command installer: newest version, settings and models kept."""
    import subprocess
    if sys.platform == "darwin":
        return subprocess.call(["bash", "-c", "LM_SKIP_VOICE=1 bash <(curl -fsSL " + INSTALL_URL.replace("install.ps1", "install.sh") + ")"])
    if os.name != "nt":
        print("update: pull the repo instead"); return 1
    print("Updating Lazy-Monster (this window will show the installer)...")
    return subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                            f"$env:LM_SKIP_VOICE='1'; irm {INSTALL_URL} | iex"])


def cmd_permissions(a, cfg):
    """macOS: open the three privacy panes Lazy-Monster needs."""
    if sys.platform != "darwin":
        print("Only needed on macOS."); return 0
    import subprocess
    panes = [("Microphone", "Privacy_Microphone", "so it can hear you"),
             ("Accessibility", "Privacy_Accessibility", "so it can click and type for you"),
             ("Automation", "Privacy_Automation", "so it can drive Word, PowerPoint and other apps"),
             ("Input Monitoring", "Privacy_ListenEvent", "for the push-to-talk hotkey")]
    print("macOS keeps these switches in System Settings > Privacy & Security.")
    print("Turn Lazy-Monster (it may show as Python or Terminal) on in each pane:")
    for name, pane, why in panes:
        input(f"  {name}: {why}. Press Enter to open it…")
        subprocess.run(["open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"])
    return 0


def cmd_models(a, cfg):
    """Download and prepare on-device models, and report where they run."""
    from .stt_refine import make_refiner
    from .tts import KokoroVoice
    t = time.perf_counter()
    kv = KokoroVoice(cfg.kokoro_voice, cfg.kokoro_speed, cfg.kokoro_quality).load()
    print(f"  voice: Kokoro-82M ({cfg.kokoro_quality}) voice {cfg.kokoro_voice} on CPU, ready in {time.perf_counter() - t:.1f} s")
    r = make_refiner(cfg, cfg.vocabulary)
    try:
        from .platform_info import IS_MAC
        if IS_MAC:
            from .stt_sherpa import ensure_model
            ensure_model()
            print("  streaming speech: sherpa-onnx Zipformer on CPU, ready", flush=True)
        r.ensure()
        print("  preparing the accurate speech model (first time can take a few minutes)…", flush=True)
        dev = r.load()
    except Exception as e:
        print(f"  speech model not ready: {e}")
        return 1
    prompt = f"vocabulary prompt {r.prompt_words} words" if r.prompt_words else "no vocabulary prompt (did not fit on this device)"
    print(f"  speech: {r.repo} on {dev}, ready in {r.load_s} s, {prompt}" + (f" (skipped: {r.errors})" if r.errors else ""))
    import numpy as np
    t = time.perf_counter()
    r.transcribe(np.zeros(16000 * 3, dtype="float32"))
    print(f"  speech: 3 s of audio transcribed in {(time.perf_counter() - t) * 1000:.0f} ms on {dev}")
    if not a.quiet:
        kv.speak("Hi, I'm Lazy-Monster. My voice runs on your laptop now.")
    return 0


def cmd_text(a, cfg):
    cfg.always_listen = True
    _, _, engine = _build(cfg, not a.execute, _file_logger(cfg), make_feedback(False), synchronous=True)
    print("Type commands (Ctrl+C to quit). Actions are dry-run unless --execute.")
    lid = 0
    try:
        for line in sys.stdin if not sys.stdin.isatty() else iter(lambda: input("> "), None):
            lid += 1
            engine.on_complete(lid, line.strip())
    except (KeyboardInterrupt, EOFError):
        pass


def _load_cases(path):
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            yield r["utterance"], r["intent"], json.loads(r.get("args") or "{}")


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else float("nan")


def cmd_bench_text(a, cfg):
    _, grammar, _ = _build(cfg, True, use_agent=False)
    ok, n, lat, misses = 0, 0, [], []
    for utt, want, args in _load_cases(a.csv):
        t0 = time.perf_counter()
        got = grammar.parse(utt)
        lat.append((time.perf_counter() - t0) * 1e3)
        n += 1
        want_i = None if want == "none" else Intent.make(want, **args)
        if (got is None and want_i is None) or (got and want_i and got.same_as(want_i)):
            ok += 1
        else:
            misses.append((utt, want, args, got.name if got else None, got.args if got else None))
    print(f"grammar accuracy {ok}/{n} = {100 * ok / max(n, 1):.1f}%   "
          f"parse p50 {_pct(lat, 50):.3f} ms  p95 {_pct(lat, 95):.3f} ms")
    for m in misses:
        print(f"  MISS {m[0]!r}: want {m[1]} {m[2]}, got {m[3]} {m[4]}")
    return 0 if not misses else 1


def cmd_record(a, cfg):
    import wave
    import sounddevice as sd
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rows = [r for r in _load_cases(a.csv) if r[1] not in ("none", "confirm_yes", "confirm_no")]
    labels = out / "labels.csv"
    with open(labels, "w", newline="", encoding="utf-8") as lf:
        w = csv.writer(lf); w.writerow(["file", "utterance", "intent", "args"])
        for i, (utt, intent, args) in enumerate(rows):
            input(f"[{i + 1}/{len(rows)}] Press Enter, then say: “Hey Monster, {utt}”")
            audio = sd.rec(int(a.seconds * 16000), samplerate=16000, channels=1, dtype="int16")
            sd.wait()
            fn = f"{i:03d}.wav"
            with wave.open(str(out / fn), "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000); wf.writeframes(audio.tobytes())
            w.writerow([fn, utt, intent, json.dumps(args)])
    print(f"saved {len(rows)} clips + {labels}")


def _speech_end(samples, sr, thresh=0.02, frame=0.02):
    n = int(sr * frame); end = 0
    for i in range(0, len(samples) - n, n):
        seg = samples[i:i + n]
        if (sum(x * x for x in seg) / n) ** 0.5 > thresh:
            end = i + n
    return end / sr


def cmd_bench_audio(a, cfg):
    from moonshine_voice import Transcriber, get_model_for_language, load_wav_file
    from .stt import make_listener, model_arch
    cfg.model = a.model or cfg.model
    events = []
    clock = time.monotonic

    def logger(line):
        ev = json.loads(line); ev["t"] = clock(); events.append(ev)

    apps, grammar, engine = _build(cfg, True, logger, clock=clock, synchronous=True, use_agent=False)
    path, arch = get_model_for_language("en", model_arch(cfg.model))
    tr = Transcriber(model_path=path, model_arch=arch)
    try:
        tr.set_keyterms(apps.keyterms())
    except Exception:
        pass
    rows, d = [], Path(a.dir)
    with open(d / "labels.csv", newline="", encoding="utf-8") as f:
        cases = list(csv.DictReader(f))
    for c in cases:
        samples, sr = load_wav_file(str(d / c["file"]))
        end_s = _speech_end(samples, sr)
        events.clear(); engine.reset()
        stream = tr.create_stream(update_interval=cfg.update_interval)
        stream.add_listener(make_listener(engine.on_partial, engine.on_complete))
        stream.start()
        t0, chunk = clock(), int(0.1 * sr)
        for i in range(0, len(samples), chunk):
            stream.add_audio(samples[i:i + chunk], sr)
            sleep = t0 + (i + chunk) / sr - clock()
            if sleep > 0:
                time.sleep(sleep)                    # real-time feed, like a microphone
        stream.stop(); stream.close()
        fired = next((e for e in events if e["event"] in ("dispatched", "needs_confirm")), None)
        want = Intent.make(c["intent"], **json.loads(c["args"] or "{}"))
        got = Intent.make(fired["intent"], **fired.get("args", {})) if fired else None
        ok = bool(got and got.same_as(want))
        tta = (fired["t"] - (t0 + end_s)) * 1000 if fired else None
        rows.append((c["file"], ok, tta, fired.get("early") if fired else None))
        print(f"{c['file']}  {'OK  ' if ok else 'FAIL'}  "
              f"{'—' if tta is None else f'{tta:+7.0f} ms'}  {'early' if fired and fired.get('early') else ''}  "
              f"heard→ {fired['intent'] + ' ' + str(fired.get('args')) if fired else 'nothing'}")
    t = [r[2] for r in rows if r[1] and r[2] is not None]
    acc = sum(r[1] for r in rows) / max(len(rows), 1) * 100
    early = sum(1 for r in rows if r[1] and r[3]) / max(sum(r[1] for r in rows), 1) * 100
    print(f"\ncommand success {acc:.1f}%  ·  time-to-action vs end of speech: p50 {_pct(t, 50):+.0f} ms, "
          f"p95 {_pct(t, 95):+.0f} ms  ·  fired before silence timeout: {early:.0f}%  ·  model {cfg.model}")
    print("(negative = action fired before you finished speaking; includes STT, excludes action execution)")


def cmd_do(a, cfg):
    """Run one task through the agent, live (or --dry-run), and watch it work."""
    from .tts import build_speaker
    if a.quiet:
        cfg.voice = "off"
    _, _, engine = _build(cfg, a.dry_run, _file_logger(cfg), make_feedback(cfg.beeps), synchronous=True,
                          speaker=build_speaker(cfg))
    if not engine.agent_enabled:
        print("agent unavailable: set OPENAI_API_KEY (see doctor)"); return 1
    task = " ".join(a.task)
    intent = engine.g.parse(task)
    print(f"Lazy-Monster · {'DRY RUN' if a.dry_run else 'LIVE'} · Ctrl+C to stop")
    try:
        if intent:                                   # instant command: no model needed
            engine.always_listen = True
            engine.on_complete(1, task)
        else:
            engine.log(event="task", text=task)
            engine.worker.submit_task(task)
    except KeyboardInterrupt:
        engine.worker.cancel()
        print("  stopped")
    return 0


def cmd_say(a, cfg):
    from .tts import build_speaker
    text = " ".join(a.text) or "Hi, I'm Lazy-Monster. Tell me what to do and I'll do it, eventually."
    print(f"voice = {cfg.voice}" + (f" · Kokoro {cfg.kokoro_voice}" if cfg.voice == "kokoro" else f" · {cfg.tts_model} · {cfg.tts_voice}"))
    build_speaker(cfg).say(text)
    return 0


def cmd_npu(a, cfg):
    from . import npu
    devs = npu.devices()
    if not devs:
        print("OpenVINO not available in this environment"); return 1
    for d, name in devs.items():
        print(f"  {d:<6} {name}")
    chosen = npu.select_device(cfg.accelerator)
    print(f"  accelerator = {cfg.accelerator} -> {chosen}")
    for d in [k for k in devs if k.startswith(("NPU", "GPU"))] + ["CPU"]:
        try:
            r = npu.probe(d)
            print(f"  probe {d:<6} compile {r['compile_ms']:>7} ms · inference {r['infer_ms']:>6} ms")
        except Exception as e:
            print(f"  probe {d:<6} failed: {type(e).__name__}: {str(e)[:120]}")
    if not any(k.startswith("NPU") for k in devs):
        print("  no NPU visible: update the Intel NPU driver (Device Manager -> Neural processors)")
    return 0


def cmd_doctor(a, cfg):
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"  {'OK ' if good else 'FIX'}  {label}{(' — ' + detail) if detail else ''}")

    line(in_venv(), "running inside a virtual environment", sys.prefix)
    line(sys.version_info >= (3, 11), "Python 3.11+", sys.version.split()[0])
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="input")
        line(True, "microphone", dev["name"])
    except Exception as e:
        line(False, "microphone", str(e))
    from .platform_info import IS_MAC, describe
    line(True, "platform", describe())
    if IS_MAC:
        try:
            import sherpa_onnx  # noqa
            line(True, "streaming speech (sherpa-onnx)")
        except Exception as e:
            line(False, "streaming speech (sherpa-onnx)", str(e))
        from .actions import mac
        line(mac.trusted(), "Accessibility permission (to click and type)", "run: monster permissions")
    else:
        try:
            import moonshine_voice  # noqa
            line(True, "moonshine-voice installed")
        except Exception as e:
            line(False, "moonshine-voice installed", str(e))
    if cfg.planner == "openai":
        from .secrets import get_key
        line(bool(get_key(cfg.openai_api_key_env)), f"{cfg.openai_api_key_env} set", f"agent model {cfg.openai_model}")
    elif cfg.planner == "jev":
        line(bool(cfg.jev_url), "JEV_API_URL set", "Jev client is a placeholder in this build")
    else:
        line(True, "agent disabled (planner = none)")
    if os.name == "nt":
        try:
            import win32com.client  # noqa
            line(True, "pywin32 (Word automation)")
        except Exception as e:
            line(False, "pywin32 (Word automation)", str(e))
        import winreg
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
            line(True, "Microsoft Word (desktop) registered")
        except OSError:
            line(False, "Microsoft Word (desktop) registered", "word_* tools need desktop Word")
        try:
            import warnings
            sys.coinit_flags = 2
            warnings.filterwarnings("ignore", message="Revert to STA COM threading mode")
            warnings.filterwarnings("ignore", message="Apply externally defined coinit_flags")
            import pywinauto  # noqa
            line(True, "pywinauto (drive any app)")
        except Exception as e:
            line(False, "pywinauto (drive any app)", str(e))
        from .actions.code import find_vscode
        vs = find_vscode()
        line(bool(vs), "VS Code", vs or "install VS Code for coding tasks")
    mods = [("webview", "pywebview (UI window)"), ("kokoro_onnx", "Kokoro voice runtime")]
    from .platform_info import IS_APPLE_SILICON, IS_INTEL_MAC
    if IS_APPLE_SILICON:
        mods.append(("mlx_whisper", "Whisper on the Apple GPU (MLX)"))
    elif IS_INTEL_MAC:
        mods.append(("faster_whisper", "Whisper on the CPU (faster-whisper)"))
    else:
        mods.append(("openvino_genai", "OpenVINO GenAI (Whisper on NPU)"))
    for mod, label in mods:
        try:
            __import__(mod)
            line(True, label)
        except Exception as e:
            line(False, label, str(e)[:80])
    from .models import models_dir
    kdir = models_dir() / "kokoro"
    wdir = models_dir() / cfg.stt_model.replace("/", "__")
    line(any(kdir.glob("*.onnx")) if kdir.exists() else False, "Kokoro model downloaded", "run: monster models")
    if not IS_MAC:
        line((wdir / "openvino_encoder_model.xml").exists(), "Whisper model downloaded", "run: monster models")
    from .wakeword import model_path as wake_model
    line(wake_model().exists(), "Hey Monster wake-word model trained", "run: monster wake-train")
    from .voicelock import print_path
    line(print_path().exists(), "voice lock enrolled", "run: monster voice-enroll")
    if not IS_MAC:
        from . import npu
        devs = npu.devices()
        npus = [f"{k}: {v}" for k, v in devs.items() if k.startswith("NPU")]
        line(bool(devs), "OpenVINO", ", ".join(devs) or "not installed")
        line(bool(npus), "Intel NPU", npus[0] if npus else "not visible; update the NPU driver")
    from .actions.files import out_dir
    line(True, "output folder", str(out_dir()))
    print("\nall good" if ok else "\nfix the items marked FIX")
    return 0 if ok else 1


def cmd_apps(a, cfg):
    apps = AppIndex()
    for k in sorted(apps.apps):
        print(k)
    print(f"\n{len(apps.apps)} apps · keyterms sent to STT: {len(apps.keyterms())}")


def main(argv=None):
    p = argparse.ArgumentParser("monster", description="Local-first voice control and voice agent for Windows")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help="path to config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="listen on the microphone")
    r.add_argument("--dry-run", action="store_true", help="print actions instead of executing")
    r.add_argument("--always", action="store_true", help="no wake phrase needed")
    r.add_argument("--model", choices=["tiny", "small", "medium"])
    r.add_argument("--device", help="input device index or name")
    r.add_argument("-v", "--verbose", action="store_true", help="print every finished line")
    r.add_argument("--quiet", action="store_true", help="no spoken replies")
    t = sub.add_parser("text", help="type commands instead of speaking")
    t.add_argument("--execute", action="store_true")
    b = sub.add_parser("bench-text", help="grammar accuracy + parse latency")
    b.add_argument("csv", nargs="?", default=str(Path(__file__).parent / "data" / "commands.csv"))
    rc = sub.add_parser("record", help="record a spoken test set")
    rc.add_argument("out"); rc.add_argument("--csv", default=str(Path(__file__).parent / "data" / "commands.csv"))
    rc.add_argument("--seconds", type=float, default=4.0)
    ba = sub.add_parser("bench-audio", help="end-to-end time-to-action on recorded clips")
    ba.add_argument("dir"); ba.add_argument("--model", choices=["tiny", "small", "medium"])
    sub.add_parser("apps", help="list resolvable apps")
    u = sub.add_parser("ui", help="the Lazy-Monster window (default)")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--quiet", action="store_true")
    u.add_argument("--device", help="input device index or name")
    u.add_argument("--background", action="store_true", help="start hidden; show on Hey Monster (used at sign-in)")
    sv = sub.add_parser("service", help="run Lazy-Monster in the background from sign-in")
    sv.add_argument("action", choices=["install", "uninstall", "start", "stop", "status"])
    wt = sub.add_parser("wake-train", help="train your personal Hey Monster wake word (NPU)")
    wt.add_argument("--samples", type=int, default=15)
    wt.add_argument("--no-record", action="store_true", help="synthetic voices only (no recording)")
    wtt = sub.add_parser("wake-test", help="live meter for the Hey Monster wake word")
    wtt.add_argument("--seconds", type=int, default=20)
    sub.add_parser("voice-enroll", help="record your voiceprint for the voice lock")
    sub.add_parser("update", help="update to the newest version (keeps your settings and models)")
    sub.add_parser("permissions", help="macOS: open the privacy settings it needs")
    vt = sub.add_parser("voice-test", help="check whether the voice lock recognises a voice")
    vt.add_argument("--times", type=int, default=3)
    mo = sub.add_parser("models", help="download and prepare local speech and voice models")
    mo.add_argument("--quiet", action="store_true")
    d = sub.add_parser("do", help="run one task with the agent and watch it work")
    d.add_argument("task", nargs="+")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--quiet", action="store_true", help="no spoken replies")
    sy = sub.add_parser("say", help="test the monster's voice")
    sy.add_argument("text", nargs="*")
    sub.add_parser("npu", help="detect and benchmark NPU / GPU / CPU via OpenVINO")
    sub.add_parser("doctor", help="check environment, mic, API key, Word")
    argv = sys.argv[1:] if argv is None else argv
    a = p.parse_args(argv or ["ui"])
    require_venv()
    cfg = Config.load(a.config)
    fn = {"run": cmd_run, "text": cmd_text, "bench-text": cmd_bench_text, "record": cmd_record,
          "bench-audio": cmd_bench_audio, "apps": cmd_apps, "do": cmd_do, "npu": cmd_npu, "doctor": cmd_doctor, "say": cmd_say, "ui": cmd_ui, "models": cmd_models,
          "wake-train": cmd_wake_train, "wake-test": cmd_wake_test, "service": cmd_service,
          "voice-enroll": cmd_voice_enroll, "voice-test": cmd_voice_test, "update": cmd_update, "permissions": cmd_permissions}[a.cmd]
    sys.exit(fn(a, cfg) or 0)


if __name__ == "__main__":
    main()
