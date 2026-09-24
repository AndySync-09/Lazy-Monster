"""One state machine for the whole conversation. The UI animation, sounds,
microphone gating and wake-word handling all follow this single state, so they
can no longer drift out of sync.

  SLEEPING -> LISTENING (your turn) -> THINKING -> ACTING -> SPEAKING -> AWAITING (your reply) -> SLEEPING
"""
import random

import numpy as np
import threading
import time
from typing import Callable

from . import sounds

SLEEPING, LISTENING, THINKING, ACTING, SPEAKING, AWAITING = \
    "sleeping", "listening", "thinking", "acting", "speaking", "awaiting"
UI = {SLEEPING: "sleep", LISTENING: "listen", THINKING: "think", ACTING: "act", SPEAKING: "speak", AWAITING: "listen"}
SUB = {SLEEPING: 'say "Hey Monster"', LISTENING: "listening\u2026", THINKING: "thinking", ACTING: "working",
       SPEAKING: "speaking \u00b7 say Hey Monster to interrupt", AWAITING: "your turn"}
ACKS = ["On it.", "Sure.", "Okay.", "Got it.", "On it, give me a second."]
PROGRESS = {"code_write_file": "Writing the code now.", "code_run": "Starting it up.",
            "code_install": "Installing that, this can take a minute.", "word_insert_text": "Writing it in Word.",
            "write_in_app": "Writing it now.", "search_web": "Searching.", "read_text": "Reading it first."}


class Conversation:
    def __init__(self, engine, speaker, gate, emit: Callable[[dict], None] = lambda ev: None,
                 wake_model: bool = False, chimes: bool = True, speak_acks: bool = True, clock=time.monotonic,
                 user_name: str = "", greet: bool = True, greet_after: float = 0.7):
        self.engine, self.speaker, self.gate, self.emit = engine, speaker, gate, emit
        self.wake_model, self.chimes, self.speak_acks, self.clock = wake_model, chimes, speak_acks, clock
        self.state = SLEEPING
        self.asking = False
        self.spoke_at = 0.0
        self._before = SLEEPING
        self.task_active = False
        self.task_started = 0.0
        self.user_name, self.greet, self.greet_after = user_name, greet, greet_after
        self.recap = False                      # cli: welcome-back recap from the journal on first wake
        self.woke_at = 0.0
        self.confirm_wake = None                # cli: second opinion (Whisper hears "monster", voice lock hears you)
        self.lock = None                        # voice lock: lets you interrupt just by talking
        self.on_remind = None                   # cli: show the window, tray notification
        self.nudge_after = 300.0
        self.barge_in = True
        self._loud, self._checking, self._last_check = 0.0, False, -1e9
        self._ratios = []
        self.greet_every = 1800.0               # say "Hi Andy" at most every 30 minutes; otherwise just the chime
        self._greeted_at = -1e9
        self.listeners = []                     # callables(state) — e.g. show the window on wake
        self._lock = threading.RLock()
        self._pending_await = None
        speaker.on_start = self._speak_start
        speaker.on_end = self._speak_end
        self._apply_gate()

    # ---- state --------------------------------------------------------------------
    def set(self, state: str, sub: str = "") -> None:
        with self._lock:
            if state == self.state and not sub:
                return
            self.state = state
            if self._pending_await is not None and state != AWAITING:
                self._pending_await.cancel()
                self._pending_await = None
            self._apply_gate()
        self.emit({"type": "state", "state": UI[state], "sub": sub or SUB[state]})
        for fn in self.listeners:
            try:
                fn(state)
            except Exception:
                pass

    def _apply_gate(self):
        # The CPU transcriber hears you in every state except SLEEPING (when the NPU
        # wake word is on duty) and SPEAKING (so the monster never hears itself).
        if self.gate is not None:
            self.gate.set("idle", self.state == SLEEPING and self.wake_model)

    def _resume(self) -> str:
        if self.asking:
            return AWAITING
        if self.task_active:                     # a task is running: never fall asleep under it
            return ACTING if self._before == ACTING else THINKING
        if self.engine.worker.busy.is_set():
            return ACTING if self._before == ACTING else THINKING
        if self.clock() < self.engine.armed_until:
            return AWAITING
        return SLEEPING

    # ---- speaker hooks --------------------------------------------------------------
    def _speak_start(self):
        if getattr(self, "tap", None) is not None:
            self.tap.mark_speaking(True)
        with self._lock:
            self._before = self.state
            self.spoke_at = self.clock()
            if self.gate is not None:
                self.gate.set("speaking", True)
        self.set(SPEAKING)

    def _speak_end(self):
        time.sleep(0.2)                                          # let the room go quiet
        if getattr(self, "tap", None) is not None:
            self.tap.mark_speaking(False)
        if self.gate is not None:
            self.gate.set("speaking", False)
        self.set(self._resume())

    # ---- engine hooks ---------------------------------------------------------------
    def feedback(self, kind: str) -> None:
        if kind == "armed":
            fresh = self.state == SLEEPING
            if fresh:
                sounds.play("wake", self.chimes)
                self.woke_at = self.clock()
                self._told_not_you = False
            self.set(LISTENING)
            if fresh and self.greet:
                t = threading.Timer(self.greet_after, self._maybe_greet)
                t.daemon = True
                t.start()
        elif kind == "thinking":
            self.set(THINKING)
        elif kind == "confirm":
            self.set(AWAITING, "say yes or no")
        elif kind == "ok":
            sounds.play("done", self.chimes)
        elif kind == "error":
            sounds.play("error", self.chimes)
        elif kind == "unknown":
            self.set(AWAITING if self.clock() < self.engine.armed_until else SLEEPING, "didn't catch that")
        elif kind == "cancelled":
            self.set(SLEEPING, "cancelled")
        elif kind == "followup":
            # let the check-mark play, then hand the turn back to the user
            t = threading.Timer(1.4, lambda: self.state in (SLEEPING, THINKING, ACTING) and self.set(AWAITING))
            t.daemon = True
            self._pending_await = t
            t.start()

    def log(self, ev: dict) -> None:
        e = ev.get("event")
        if e == "task":
            self.asking = False
            self.task_active, self.task_started = True, self.clock()
            self.set(THINKING)
            if self.speak_acks and not str(ev.get("text", "")).lower().startswith("yes, please do that"):
                threading.Thread(target=self.speaker.say, args=(random.choice(ACKS),), daemon=True).start()
        elif e == "step":
            if self.state != SPEAKING:
                self.set(ACTING)
        elif e == "asking":
            self.asking = True
            self.set(AWAITING, "your answer")
        elif e == "heard_during_task":
            self.asking = False
            self.set(THINKING)
        elif e in ("agent_done", "task_error"):
            self.asking = False
            self.task_active = False
        elif e == "not_you":
            # Say so once per wake, instead of silently ignoring you if the voiceprint is off
            if self.clock() - self.woke_at < 20 and not getattr(self, "_told_not_you", False):
                self._told_not_you = True
                hint = "That didn't sound like you, so I'm ignoring it. Press Control Alt Space if it was you."
                self.emit({"type": "say", "text": hint})
                threading.Thread(target=self.speaker.say, args=(hint,), daemon=True).start()

    def greeting(self) -> str:
        from .userinfo import GREETINGS
        if not getattr(self, "_recapped", False) and self.recap:
            self._recapped = True
            try:
                from . import journal
                rec = journal.recap()
            except Exception:
                rec = ""
            if rec:
                hello = f"Welcome back{', ' + self.user_name if self.user_name else ''}."
                line = f"{hello} {rec} Want to pick one of those up, or start fresh?"
                agent = self.engine.worker.agent
                if agent is not None:
                    agent.seed(line)                 # so "the snake game" or "fresh" is understood
                return line
        if not self.user_name:
            return random.choice(["How can I help?", "Yes?", "What can I do for you?"])
        return random.choice(GREETINGS).format(name=self.user_name)

    def _maybe_greet(self) -> None:
        """Greet only if you paused after "Hey Monster". If you went straight on
        ("Hey Monster, open Notepad"), it just listens: no talking over you."""
        if self.state != LISTENING or self.engine.turn is not None or self.speaker.speaking:
            return
        if self.engine.last_partial >= self.woke_at:
            return
        recap_due = self.recap and not getattr(self, "_recapped", False)
        if not recap_due and self.clock() - self._greeted_at < self.greet_every:
            return                                # woke recently: the chime is enough
        self._greeted_at = self.clock()
        g = self.greeting()
        self.emit({"type": "say", "text": g})
        self.speaker.say(g)

    def progress(self, tool: str) -> None:
        """Called once if a task runs long: one short spoken update, never a play-by-play."""
        phrase = PROGRESS.get(tool)
        if phrase:
            threading.Thread(target=self.speaker.say, args=(phrase,), daemon=True).start()

    # ---- reminders that come to you -----------------------------------------------------------
    def remind(self, r: dict, late: bool = False) -> None:
        """A reminder is due: wake up, say it, suggest what to do next, and wait for your pick.
        Nothing is done until you choose."""
        from datetime import datetime
        when = datetime.fromisoformat(r["when"]).strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")
        if self.on_remind:
            try:
                self.on_remind(r)
            except Exception:
                pass
        sounds.play("wake", self.chimes)
        who = f"{self.user_name}, " if self.user_name else ""
        head = f"{who}you had a reminder at {when}: {r['what']}." if late else f"{who}it's {when}. Reminder: {r['what']}."
        agent = self.engine.worker.agent
        ideas = agent.suggest(r["what"]) if agent is not None else []
        if ideas:
            opts = ", ".join(ideas[:-1]) + (", or " if len(ideas) > 1 else "") + ideas[-1]
            line = f"{head} I could {opts[0].lower() + opts[1:]}. Want me to do one of those?"
            agent.seed(f"{line}\n(Options I offered: " + "; ".join(f"{i + 1}) {x}" for i, x in enumerate(ideas))
                       + ". Do nothing until the user picks one.)")
            agent.last_said = line
        else:
            line = head
        self.engine.log(event="reminder_fired", what=r["what"], late=late, ideas=ideas)
        self.emit({"type": "say", "text": line})
        self.speaker.say(line)
        fired_at = self.clock()
        self.engine.armed_until = self.clock() + 45
        self.engine.armed_source = "followup"
        self.set(AWAITING, "reminder: your pick")

        def nudge():                               # brushing your teeth? one gentle repeat
            from . import reminders
            if self.engine.last_activity < fired_at and not r.get("nudged"):
                reminders.mark(r["id"], nudged=True)
                again = f"Just checking: {r['what']}." + (" Want me to start on something?" if ideas else "")
                if agent is not None and ideas:
                    agent.seed(f"{again}\n(Options I offered earlier: " + "; ".join(ideas) + ".)")
                self.emit({"type": "say", "text": again})
                self.speaker.say(again)
                self.engine.armed_until = self.clock() + 45
                self.engine.armed_source = "followup"
        t = threading.Timer(self.nudge_after, nudge)
        t.daemon = True
        t.start()

    # ---- interrupting by just talking -----------------------------------------------------
    def playback_level(self, now: float) -> float:
        """How loud the monster's own voice is right now (what the mic hears as echo)."""
        k = getattr(self.speaker, "kokoro", None)
        pl = getattr(k, "playing", None) if k is not None else None
        if not pl:
            return 0.0
        audio, sr, start = pl
        t = now - start
        i0, i1 = int(max(0.0, t - 0.25) * sr), int(max(0.0, t + 0.05) * sr)
        seg = audio[i0:i1]
        return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0

    def on_audio(self, block) -> None:
        """Mic blocks while the monster talks. Interrupting works by loudness against its
        own echo: while it speaks, the mic hears its voice at a steady ratio; when you talk
        over it, the mic gets much louder than that ratio explains. The voice lock, when
        on, only vetoes voices that are clearly someone else (a TV)."""
        if self.state != SPEAKING or not self.barge_in:
            self._loud, self._ratios = 0.0, getattr(self, "_ratios", [])[-40:]
            return
        now = time.monotonic()
        mic = float(np.sqrt(np.mean(np.asarray(block, dtype=np.float32) ** 2)))
        play = self.playback_level(now)
        ratios = getattr(self, "_ratios", [])
        if play > 0.02 and self._loud == 0.0:
            ratios.append(mic / play)
            self._ratios = ratios[-40:]
        echo = float(np.median(self._ratios)) if len(self._ratios) >= 8 else 1.0
        over = mic > max(0.018, 2.5 * echo * play + 0.01)
        self._loud = self._loud + len(block) / 16000 if over else max(0.0, self._loud - len(block) / 32000)
        if self._loud < 0.35 or self._checking or self.clock() - self.spoke_at < 0.5:
            return
        self._checking = True
        tap = getattr(self, "tap", None)

        def go():
            try:
                if self.lock is not None and tap is not None:
                    ok, score = self.lock.check(tap.raw(1.0))
                    if not ok and 0 <= score < 0.35:            # clearly not you: a TV, someone else
                        self.engine.log(event="barge_vetoed", score=round(float(score), 3))
                        return
                self.engine.barge_t = self.clock() - 1.0
                self.speaker.interrupt()
                self.engine.log(event="barge_in")
                self.engine.wake_up("barge-in")
            finally:
                self._checking, self._loud = False, 0.0
        threading.Thread(target=go, daemon=True).start()

    # ---- wake word -------------------------------------------------------------------
    def on_wake(self, score: float) -> None:
        s = self.state
        if s == SLEEPING:
            if self.confirm_wake is None:
                self.engine.wake_up()
                return

            def check():                          # a false wake stays silent: no chime, no greeting, no window
                try:
                    ok, why = self.confirm_wake()
                except Exception:
                    ok, why = True, "check failed"
                if ok and self.state == SLEEPING:
                    self.engine.wake_up()
                else:
                    self.engine.log(event="wake_rejected", why=why, score=round(score, 3))
            threading.Thread(target=check, daemon=True).start()
        elif s == SPEAKING:
            # barge-in, but never on the first moment of its own voice, and only when sure
            if self.clock() - self.spoke_at > 0.8 and score >= 0.95:
                self.speaker.interrupt()
                sounds.play("wake", self.chimes)
                self.engine.wake_up()
        # LISTENING / AWAITING / THINKING / ACTING: already listening; no beep, no re-arm

    def push_to_talk(self) -> None:
        """Hotkey or a click on the orb: listen now, no wake word, no voice lock for this request."""
        if self.state == SPEAKING:
            self.speaker.interrupt()
        self.engine.trust(self.engine.armed_window + 30)
        if self.state in (THINKING, ACTING):
            self.set(self.state, "go ahead, I'm listening")
            return
        if self.state != SLEEPING:
            self.set(SLEEPING)                                     # so the wake chime and greeting run
        self.engine.wake_up("push-to-talk")

    # ---- heartbeat ---------------------------------------------------------------------
    def tick(self) -> None:
        self.engine.poll()
        if self.task_active:
            if not self.engine.worker.busy.is_set() and self.clock() - self.task_started > 5:
                self.task_active = False                 # the worker finished without telling us
            elif self.state in (THINKING, ACTING) and self.clock() - self.task_started > 8:
                secs = int(self.clock() - self.task_started)
                if secs % 4 == 0 and secs != getattr(self, "_pulse", -1):
                    self._pulse = secs                   # "still working" so a slow brain doesn't look asleep
                    self.emit({"type": "state", "state": UI[self.state], "sub": f"still working\u2026 {secs} s"})
            return
        if self.state in (LISTENING, AWAITING) and not self.asking and self.engine.turn is None \
                and not self.engine.busy() and not self.speaker.speaking:
            self.set(SLEEPING)

    def run_ticker(self, stop: threading.Event) -> None:
        def loop():
            while not stop.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                time.sleep(0.1)
        threading.Thread(target=loop, daemon=True, name="lazymonster-conversation").start()
