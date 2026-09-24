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
                try:
                    worker.agent.escalation = build_client(cfg, escalation=True)
                except Exception:
                    worker.agent.escalation = None
        except AgentError as e:
            print(f"  agent off: {e}", file=sys.stderr)
    engine = Engine(grammar, WakeSpotter(cfg.wake_names, require_prefix=cfg.require_prefix),
                    worker, agent_enabled=worker.agent is not None, feedback=feedback,
                    stable_updates=cfg.stable_updates, always_listen=cfg.always_listen,
                    logger=logger, clock=clock, say=say, on_exit=on_exit)
    if worker.agent is not None:
        worker.agent.on_sleep = engine.go_to_sleep
    from .jev import build_jev
    jev = build_jev(cfg, log=log)
    if jev is not None:
        engine.jev = jev
        if worker.agent is not None:
            worker.agent.jev = jev
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
        elif e == "not_you":
            print(f"  voice lock: not your voice (similarity {ev.get('score')}); ignored", flush=True)
        elif e == "wake_rejected":
            print(f"  wake ignored ({ev.get('why')}, score {ev.get('score')})", flush=True)
        elif e == "not_for_me":
            print(f"  ignored (Jev: not meant for me, p={ev.get('p')}): {ev.get('text')}", flush=True)
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
            info["refiner"] = r
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

    status("opening the microphone…")
    mic = open_mic(cfg.model, cfg.update_interval, keyterms, part, comp, device=getattr(a, "device", None))
    gate.mic = mic
    mic.start()
    info["lock"] = "voice lock off"
    if cfg.voice_lock:
        try:
            from .voicelock import load_lock_process
            status("starting the voice lock (separate helper process)…")
            lock = load_lock_process()
            if lock is None:
                status("voice lock: not enrolled (monster voice-enroll) - anyone can command it")
            else:
                engine.verify = lambda t0: lock.check(tap.slice(t0))
                info["lock"] = "voice lock on"
                info["lock_obj"] = lock
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
            if det is not None and cfg.wake_confirm and info.get("refiner") is not None:
                import re as _re
                heard_monster = _re.compile(r"mon\s?st|nster|m[ao]nst|monster|master|mobster", _re.I)

                def confirm():
                    t = tap.clock()
                    text = info["refiner"].transcribe(tap.slice(t - 2.2, t, preroll=0), prompt=False) or ""
                    if not heard_monster.search(text):
                        return False, f"whisper heard {text[:40]!r}"
                    lk = info.get("lock_obj")
                    if lk is not None:
                        ok, sc = lk.check(tap.slice(t - 2.2, t, preroll=0))
                        if not ok and sc >= 0 and sc < lk.threshold - 0.15:   # short clip: be lenient
                            return False, f"not your voice ({sc:.2f})"
                    return True, text[:40]
                conv.confirm_wake = confirm
                status("wake word: double-checked by Whisper" + (" and your voice" if info.get("lock_obj") else ""))
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


BRAIN_COLORS = {"openai": "#10A37F", "anthropic": "#E08A5E", "claude": "#E08A5E", "local": "#9DB8FF"}


def status_event(cfg, agent_enabled: bool, info: dict, voice: str) -> dict:
    """The animated status bar: ears, brain, lock, chips (details on hover)."""
    wake = info.get("wake", "")
    dev = "NPU" if "NPU" in wake else ("CPU" if "CPU" in wake else "")
    p = cfg.planner.lower()
    short = {"openai": cfg.openai_model, "anthropic": "Claude " + cfg.anthropic_model.replace("claude-", "").split("-2")[0],
             "claude": "Claude", "local": "Local \u00b7 " + (cfg.local_model or "model")}.get(p, "")
    if (cfg.decider or "") == "jev" and short:
        short += " + Jev"
    return {"type": "status", "wake_dev": dev or "ears",
            "wake_title": f"{wake}. {info.get('stt', '')}." + (f" Push-to-talk: {info['ptt']}." if info.get("ptt") else ""),
            "brain": short if agent_enabled else "", "big": bool(cfg.go_big and agent_enabled),
            "brain_title": ("Brain: " + brain_label(cfg, agent_enabled) + (" \u00b7 goes big on hard tasks" if cfg.go_big else ""))
                           if agent_enabled else "No brain yet: quick commands only. Run the installer to add one.",
            "brain_color": BRAIN_COLORS.get(p, ""), "lock": info.get("lock") == "voice lock on",
            "chips_title": f"NPU: wake word \u00b7 {info.get('stt', 'Whisper')} \u00b7 CPU: {voice}"}


def brain_label(cfg, enabled=True) -> str:
    if not enabled:
        return "agent off"
    p = cfg.planner.lower()
    base = {"openai": cfg.openai_model, "anthropic": cfg.anthropic_model, "claude": cfg.anthropic_model,
            "local": f"local {cfg.local_model} at {cfg.local_base_url}"}.get(p, p)
    return base + (" + Jev" if (cfg.decider or "").lower() == "jev" else "")


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
          f"{brain_label(cfg, engine.agent_enabled)}"
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
    import faulthandler
    faulthandler.enable(file=f)          # a native crash still leaves a trace in the log
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
        voice = {"kokoro": f"Kokoro {cfg.kokoro_voice}", "openai": "OpenAI voice", "windows": "Windows voice"}.get(cfg.voice, "silent")
        bus.emit(status_event(cfg, engine.agent_enabled, info, voice))
        conv.set("sleeping", 'say "Hey Monster" or type below')

    # "Hey Monster, sleep" shrinks to a small sleeping orb and keeps listening, in every UI mode.
    # "Hey Monster", the hotkey or a click on the orb brings the full window back. Quit is in the tray.
    from . import conversation as C
    engine.exit_message = "Okay. I'll be right here, just say Hey Monster."
    engine.on_move = bus.move_to
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
        run_window(bus, api, backend, stop, hidden=background,
                   saved_pos=(cfg.window_x, cfg.window_y) if cfg.window_x >= 0 else None)
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
    from . import tui
    from .tts import KokoroVoice
    from .wake_train import build, fit
    from .wakeword import Features, model_path
    tui.enable()
    tui.monster(sleepy=True)
    tui.title("Teach the monster your wake word")
    tui.dim("Everything stays on this PC. About 3 minutes.")
    kv = KokoroVoice(cfg.kokoro_voice, cfg.kokoro_speed, cfg.kokoro_quality, cfg.kokoro_model_path, cfg.kokoro_voices_path).load()
    feats = Features("CPU")                           # training batch runs on CPU; detection runs on the NPU
    user_pos, user_neg = [], []
    if not a.no_record:
        rec = tui.Recorder(getattr(a, "device", None))
        tui.say("First, a second of quiet so I know what your room sounds like…")
        rec.calibrate(1.0)
        tui.title(f"Say \"Hey Monster\" {a.samples} times, the way you normally would.")
        tui.dim("Just talk. I start when you speak and stop when you pause.")
        misses = 0
        while len(user_pos) < a.samples and misses < 8:
            clip = rec.take(f"{tui.dots(len(user_pos), a.samples)}  Hey Monster", max_s=3.0)
            if clip is None:
                misses += 1
                tui.warn("Didn't hear anything. Speak up a little, or move closer.")
                continue
            user_pos.append(clip)
            tui.ok(f"{len(user_pos)}/{a.samples}  {tui.cheer()}")
        tui.title("Now the opposite: things that are NOT the wake word.")
        for i in range(3):
            tui.say(f"Talk about anything for 6 seconds ({i + 1}/3). Your day, lunch, the weather…")
            user_neg.append(rec.timed("chatting", 6.0))
            tui.ok("Perfect, that's not me.")
        tui.say("Now 20 seconds of your normal room: type, click, let the fan run. Don't say the wake word.")
        room = rec.timed("room sounds", 20.0)
        user_neg += [room[i:i + 16000 * 5] for i in range(0, len(room) - 16000 * 5 + 1, 16000 * 5)]
        tui.ok("Got your room. That's what false wakes are made of.")
        tui.say("Last one: stay quiet for 5 seconds.")
        user_neg.append(rec.timed("quiet", 5.0))
        tui.ok("Shhh. Done.")
    tui.title("Building your wake word (a few minutes)…")
    pos, neg = build(kv.k, feats, user_pos, user_neg, log=tui.dim)
    head, report = fit(pos, neg)
    head.save(model_path(), **report)
    tui.monster()
    tui.ok(f"Saved. Catches {report['recall']:.0%} of held-out \"Hey Monster\"s; "
           f"false wakes {report['false_positive_rate']:.2%} per window.")
    tui.dim("Test it any time: monster wake-test. It takes effect the next time the monster starts.")
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
        print(f"  brain: {brain_label(cfg)} · voice lock: {'on' if cfg.voice_lock else 'off'} · push-to-talk: {cfg.push_to_talk or 'off'}")
        from .config import config_dir
        log = config_dir() / "monster.log"
        print(f"  log: {log}")
        if log.exists():
            lines = log.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            start = max((i for i, l in enumerate(lines) if "background start" in l), default=0)
            keys = ("wake word", "push-to-talk", "voice lock", "accurate speech", "microphone", "error", "Error",
                    "Traceback", "Fatal", "off (", "taken")
            recent = [l for l in lines[start:] if any(k in l for k in keys)][-12:]
            if recent:
                print("  since the last start:")
                for l in recent:
                    print("    " + l.strip())
    return 0


def cmd_voice_enroll(a, cfg):
    """Record your voiceprint so the monster only acts on you."""
    from . import tui
    from .config import save_setting
    from .voicelock import ENROLL_SENTENCES, VoiceLock, print_path
    import numpy as np
    tui.enable()
    tui.monster()
    tui.title("Voice lock: so the monster only listens to you")
    tui.dim("Read each sentence in your normal voice. It stops by itself when you finish.")
    v = VoiceLock()
    rec = tui.Recorder(getattr(a, "device", None))
    rec.calibrate(1.0)

    def one(sentence, n):
        for _ in range(3):
            tui.say(f"{tui.P}{n}/{len(ENROLL_SENTENCES)}{tui.R}  \"{sentence}\"")
            clip = rec.take("reading", max_s=9.0, min_speech=1.2, end_silence=0.9, wait_s=8.0)
            if clip is not None and len(clip) > 16000 * 1.5:
                return clip
            tui.warn("I only caught part of that. Once more, the whole sentence.")
        return None

    clips = [one(s, i + 1) for i, s in enumerate(ENROLL_SENTENCES)]
    if any(c is None for c in clips):
        tui.warn("Couldn't record every sentence. Voice lock stays off. Try again: monster voice-enroll")
        return 1
    # re-record any take that doesn't sound like the others (a cough, a noise, a half sentence)
    for attempt in range(2):
        embs = [v.embed(c) for c in clips]
        bad = []
        for i, e in enumerate(embs):
            rest = np.mean([x for j, x in enumerate(embs) if j != i], axis=0)
            if float(e @ (rest / np.linalg.norm(rest))) < 0.55:
                bad.append(i)
        if not bad:
            break
        tui.warn(f"{len(bad)} take(s) didn't sound like the others. Let's redo those.")
        for i in bad:
            c = one(ENROLL_SENTENCES[i], i + 1)
            if c is not None:
                clips[i] = c
    rep = v.enroll(clips)
    if rep["self_mean"] < 0.6:
        tui.warn(f"Your takes didn't match each other well (score {rep['self_mean']:.2f}, noisy room?). "
                 "Voice lock stays off so it can't lock you out. Try again somewhere quieter.")
        save_setting("voice_lock", False)
        print_path().unlink(missing_ok=True)
        return 1
    p = v.save()
    save_setting("voice_lock", True)
    tui.ok(f"Voice lock on. Your consistency {rep['self_mean']:.2f}, threshold {rep['threshold']:.2f}.")
    tui.dim(f"Saved {p}. Check it: monster voice-test. Turn it off: monster voice-lock off")
    return 0


def cmd_voice_reset(a, cfg):
    """Forget the trained wake word and voiceprint; with --train, retrain both now."""
    from . import service, tui
    from .config import save_setting
    from .voicelock import print_path
    from .wakeword import model_path
    tui.enable()
    was_running = bool(service.running()) if (os.name == "nt" or sys.platform == "darwin") else False
    if was_running:
        service.stop()
        time.sleep(1.0)
    for p in (model_path(), print_path()):
        p.unlink(missing_ok=True)
    save_setting("voice_lock", False)
    tui.ok("Forgot your wake word and voiceprint.")
    rc = 0
    if a.train:
        rc = cmd_wake_train(argparse.Namespace(samples=15, no_record=False, device=None), cfg)
        cmd_voice_enroll(argparse.Namespace(device=None), cfg)
    if was_running:
        service.start()
        tui.ok("The monster is back up with your new voice.")
    return rc


def cmd_voice_lock(a, cfg):
    from .config import save_setting
    on = a.state == "on"
    save_setting("voice_lock", on)
    print(f"  voice lock {'on' if on else 'off'}; it applies the next time the monster starts "
          "(monster service stop ; monster service start)")
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
        return subprocess.call(["bash", "-c", f"LM_SKIP_VOICE=1 LM_BRAIN={cfg.planner} "
                                f"LM_JEV={'y' if cfg.decider == 'jev' else 'n'} bash <(curl -fsSL "
                                + INSTALL_URL.replace("install.ps1", "install.sh") + ")"])
    if os.name != "nt":
        print("update: pull the repo instead"); return 1
    print("Updating Lazy-Monster (this window will show the installer)...")
    return subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                            f"$env:LM_SKIP_VOICE='1'; $env:LM_BRAIN='keep'; "
                            f"$env:LM_JEV='{'y' if cfg.decider == 'jev' else 'n'}'; irm {INSTALL_URL} | iex"])


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
    kv = KokoroVoice(cfg.kokoro_voice, cfg.kokoro_speed, cfg.kokoro_quality, cfg.kokoro_model_path, cfg.kokoro_voices_path).load()
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


VOICES = [("af_heart", "US, warm (default)"), ("af_bella", "US, bright"), ("af_nicole", "US, soft"),
          ("af_sarah", "US, calm"), ("am_adam", "US, deep"), ("am_michael", "US, friendly"),
          ("bf_emma", "UK, clear"), ("bm_george", "UK, classic"), ("hf_alpha", "Indian English"),
          ("hf_beta", "Indian English, lighter"), ("hm_omega", "Indian English, male")]


def cmd_voices(a, cfg):
    """List voices, or hear one: monster voices --play bf_emma"""
    from . import tui
    from .tts import build_speaker
    tui.enable()
    if a.play:
        cfg.voice, cfg.kokoro_voice = "kokoro", a.play
        build_speaker(cfg).say("Hi, I'm your monster. This is how I sound. Say hey monster whenever you need me.")
        tui.dim(f"Keep it: monster voices --use {a.play}")
        return 0
    if a.use:
        from .config import save_setting
        save_setting("voice", "kokoro")
        save_setting("kokoro_voice", a.use)
        tui.ok(f"Voice set to {a.use}. It applies the next time the monster starts.")
        return 0
    tui.title("Voices (all local, Kokoro-82M)")
    for k, d in VOICES:
        mark = f"{tui.L}\u25cf{tui.R}" if k == cfg.kokoro_voice else " "
        print(f"  {mark} {k:<11} {d}")
    tui.dim("Hear one: monster voices --play hf_alpha      Keep it: monster voices --use hf_alpha")
    tui.dim("Bring your own models: see docs/VOICES.md")
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
    from .secrets import get_key
    p = cfg.planner.lower()
    if p == "openai":
        line(bool(get_key(cfg.openai_api_key_env)), f"{cfg.openai_api_key_env} set", f"brain: OpenAI {cfg.openai_model}")
    elif p in ("anthropic", "claude"):
        line(bool(get_key(cfg.anthropic_api_key_env)), f"{cfg.anthropic_api_key_env} set", f"brain: Claude {cfg.anthropic_model}")
    elif p == "jev":
        line(False, "brain", "Jev is a decision model, not a brain: set planner to openai or anthropic, decider = jev")
    else:
        line(True, "agent disabled (planner = none)")
    if (cfg.decider or "").lower() == "jev":
        from .jev import build_jev
        j = build_jev(cfg)
        ans = j.ask("Turn the volume down please.", {"q": {"type": "noul", "instructions": "Is this a request?"}}) if j else None
        line(bool(ans), "Jev decider (TypeSafe)", f"{cfg.jev_model}, answered in time" if ans else
             f"{cfg.jev_api_key_env} missing or Jev unreachable (the monster works without it)")
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
    if os.name == "nt" or sys.platform == "darwin":
        from . import service
        if service.installed():
            n = len(service.running())
            line(n == 1, "background monster running", f"{n} running; see: monster service status" if n != 1 else "")
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
    vr = sub.add_parser("voice-reset", help="forget your trained voice (and retrain with --train)")
    vr.add_argument("--train", action="store_true")
    vl = sub.add_parser("voice-lock", help="turn the voice lock on or off")
    vl.add_argument("state", choices=["on", "off"])
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
    vo = sub.add_parser("voices", help="list, hear and pick the monster's voice")
    vo.add_argument("--play", help="hear a voice, e.g. bf_emma")
    vo.add_argument("--use", help="make a voice the default, e.g. hf_alpha")
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
          "voice-enroll": cmd_voice_enroll, "voice-lock": cmd_voice_lock, "voice-reset": cmd_voice_reset, "voices": cmd_voices, "voice-test": cmd_voice_test, "update": cmd_update, "permissions": cmd_permissions}[a.cmd]
    sys.exit(fn(a, cfg) or 0)


if __name__ == "__main__":
    main()
