"""Semantic endpointing engine + three lanes.

Lane 1 (instant): grammar match on streaming partials; fires as soon as the
partial is a complete command that stayed identical for `stable_updates`
updates, instead of waiting for 0.5-0.8 s of silence.
Lane 2 (agent): anything the grammar can't parse goes, as text, to the agent
loop on the worker: the model calls typed tools one at a time, each validated
and guarded locally. "Hey Monster, stop" cancels a running task."""
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from .grammar import Grammar
from .intents import Intent
from .plans import Plan, single
from .wake import WakeSpotter

_COMPOUND = re.compile(r"\b(?:and|then|after that|also)\b", re.I)


@dataclass
class _Line:
    first_seen: float
    last: Optional[Intent] = None
    stable: int = 0
    fired: bool = False
    woke: bool = False
    armed: bool = False          # the line STARTED inside a listening window
    typed: bool = False          # came from the text box, not the microphone


class Engine:
    def __init__(self, grammar: Grammar, wake: WakeSpotter, worker, agent_enabled: bool = False,
                 feedback: Optional[Callable[[str], None]] = None, stable_updates: int = 2,
                 armed_window: float = 8.0, confirm_window: float = 8.0,
                 always_listen: bool = False, clock=time.monotonic, logger=None, followup_window: float = 15.0,
                 say: Optional[Callable[[str], None]] = None, on_exit: Optional[Callable[[], None]] = None,
                 refine: Optional[Callable[[float], Optional[str]]] = None, refine_async: bool = True,
                 turn_delay: float = 0.0):
        self.g, self.wake, self.worker, self.agent_enabled = grammar, wake, worker, agent_enabled
        self.feedback = feedback or (lambda kind: None)
        self.say = say or (lambda text: None)
        self.on_exit = on_exit or (lambda: None)
        self.refine, self.refine_async = refine, refine_async   # pass-2 recognizer (Whisper on NPU)
        self._typed_id = 0
        self.exit_message = "Going to sleep. Run monster again to wake me."
        self.followup_only_on_question = False        # cli: True
        self.verify: Optional[Callable[[float], bool]] = None   # voice lock: is this audio (since t) you?
        self.trusted_until = 0.0                                # push-to-talk: skip the voice lock until then
        self.last_activity = 0.0
        # Turn-taking: the speech model splits a sentence at every pause; a turn collects
        # those lines until you have finished (turn_delay seconds of quiet), then acts once.
        self.turn_delay = turn_delay
        self.turn: Optional[dict] = None
        self.last_partial = -1e9
        self.stable_updates = max(1, stable_updates)
        self.armed_window, self.confirm_window, self.followup_window = armed_window, confirm_window, followup_window
        self.always_listen, self.clock, self.logger = always_listen, clock, logger
        self.lines: Dict[int, _Line] = {}
        self.armed_until = 0.0
        self.pending: Optional[Plan] = None
        self.pending_until = 0.0
        self._lock = threading.RLock()

    def reset(self) -> None:
        with self._lock:
            self.lines.clear()
            self.armed_until, self.pending, self.pending_until = 0.0, None, 0.0

    # ---- helpers -------------------------------------------------------
    def _line(self, lid: int) -> _Line:
        if lid not in self.lines:
            now = self.clock()
            self.lines[lid] = _Line(first_seen=now, armed=self.always_listen or now < self.armed_until
                                    or bool(self.pending and now < self.pending_until) or self.turn is not None)
            if len(self.lines) > 64:
                for k in sorted(self.lines)[:32]:
                    self.lines.pop(k, None)
        return self.lines[lid]

    def _command(self, text: str, ln: _Line) -> Optional[str]:
        woke, cmd = self.wake.split(text)
        if woke:
            ln.woke = True
            return cmd
        # A long sentence may finish after the window closes; what counts is when it began.
        now = self.clock()
        if ln.armed or self.always_listen or now < self.armed_until or (self.pending and now < self.pending_until):
            return text.strip()
        return None

    def log(self, **kw):
        if self.logger:
            self.logger(json.dumps(kw, default=str))

    # ---- stream callbacks ---------------------------------------------
    def trust(self, seconds: float) -> None:
        self.trusted_until = self.clock() + seconds

    def _is_you(self, first_seen: float, typed: bool) -> bool:
        """Voice lock gate. Typed requests and push-to-talk are you by definition."""
        if typed or self.verify is None or self.clock() < self.trusted_until:
            return True
        try:
            ok = bool(self.verify(first_seen))
        except Exception:
            return True                                         # never lock you out on an error
        if not ok:
            self.log(event="not_you")
        return ok

    def wake_up(self, source: str = "npu") -> None:
        """The wake-word model heard "Hey Monster": listen for the command."""
        with self._lock:
            self.armed_until = self.clock() + self.armed_window
            self.last_activity = self.clock()
        self.feedback("armed")
        self.log(event="wake", source=source)

    def busy(self) -> bool:
        now = self.clock()
        return (now < self.armed_until or bool(self.pending and now < self.pending_until)
                or self.worker.busy.is_set() or now - self.last_activity < 4.0)

    def on_partial(self, lid: int, text: str) -> None:
        self.last_activity = self.last_partial = self.clock()
        with self._lock:
            ln = self._line(lid)
            if ln.fired or self.turn is not None:        # mid-turn: wait for the whole sentence
                return
            cmd = self._command(text, ln)
            if not cmd or _COMPOUND.search(cmd):
                return
            intent = self.g.parse(cmd)
            if not intent or not intent.spec["early"]:
                ln.last, ln.stable = None, 0
                return
            if intent.same_as(ln.last):
                ln.stable += 1
            else:
                ln.last, ln.stable = intent, 1
            if ln.stable >= self.stable_updates:
                self._fire_intent(ln, intent, cmd, early=True)

    def handle_text(self, text: str) -> None:
        """A typed request (UI text box, Approve/Cancel buttons): no wake phrase needed."""
        with self._lock:
            self._typed_id -= 1
            lid = self._typed_id
            ln = self._line(lid)
            ln.armed, ln.typed = True, True
        self.on_complete(lid, text)

    def go_to_sleep(self, cmd: str = "") -> None:
        self.armed_until = 0.0
        if self.worker.agent is not None:
            self.worker.agent.suggestion = ""
        self.say(self.exit_message)
        self.log(event="exit", text=cmd)
        self.on_exit()

    def _suggestion(self) -> str:
        a = self.worker.agent
        return getattr(a, "suggestion", "") if a is not None else ""

    def _agent_busy(self) -> bool:
        return bool(self.agent_enabled and self.worker.busy.is_set() and self.worker.agent is not None)

    def on_complete(self, lid: int, text: str) -> None:
        self.last_activity = self.clock()
        with self._lock:
            ln = self._line(lid)
            if ln.fired:
                return
            if self._agent_busy():                      # talking to a running task: no wake needed
                ln.fired = True
                if not self._is_you(ln.first_seen, ln.typed):
                    return
                woke, cmd = self.wake.split(text)
                cmd = (cmd if woke else text).strip()
                intent = self.g.parse(cmd) if cmd else None
                if intent and intent.name in ("confirm_no", "exit_app"):
                    self._fire_intent(ln, intent, cmd, early=False)
                elif cmd:
                    self.worker.agent.hear(cmd)
                return
            cmd = self._command(text, ln)
            if cmd is None:
                return
            if not cmd:
                if ln.woke:                     # "Lazy-Monster" ... pause ... command
                    self.armed_until = self.clock() + self.armed_window
                    self.feedback("armed")
                return
            whole = cmd if self.turn is None else " ".join(self.turn["parts"] + [cmd])
            intent = self.g.parse(whole)
            if intent:                                   # "open" + "notepad" across a pause still works
                self.turn = None
                self._fire_intent(ln, intent, whole, early=False)
                return
            ln.fired = True
            if self.turn is None:
                self.turn = {"parts": [], "first": ln.first_seen, "woke": False, "typed": ln.typed}
            self.turn["parts"].append(cmd)
            self.turn["woke"] = self.turn["woke"] or ln.woke
            self.turn["last"] = self.clock()
            if self.turn_delay <= 0 or ln.typed:
                self._finish_turn()

    def poll(self) -> None:
        """Called ~10x a second: closes the turn once you have been quiet for turn_delay."""
        with self._lock:
            if self.turn and self.clock() - max(self.turn["last"], self.last_partial) >= self.turn_delay:
                self._finish_turn()

    def in_session(self) -> bool:
        a = self.worker.agent
        if a is None:
            return False
        return bool(getattr(a, "suggestion", "")) or (self.clock() - getattr(a, "last_done", -1e9)
                                                      < getattr(a, "session_timeout", 0))

    def _finish_turn(self) -> None:
        t, self.turn = self.turn, None
        if not t:
            return
        cmd = " ".join(p.strip() for p in t["parts"]).strip()
        self.armed_until = 0.0
        if not self._is_you(t["first"], t["typed"]):
            self.feedback("unknown")
            return
        # A one-word turn is noise, unless we are mid-conversation ("snake", "the second one").
        if not self.agent_enabled or not cmd or (len(cmd.split()) < 2 and not self.in_session()):
            self.feedback("unknown")
            self.log(event="unknown", text=cmd)
            return
        self.feedback("thinking")
        if self.refine is None or t["typed"]:
            self.log(event="task", text=cmd)
            self.worker.submit_task(cmd, done=self._task_done)
        elif self.refine_async:
            threading.Thread(target=self._refine_then_submit, args=(t["first"], t["woke"], cmd), daemon=True).start()
        else:
            self._refine_then_submit(t["first"], t["woke"], cmd)

    def _refine_then_submit(self, first_seen: float, woke: bool, cmd: str) -> None:
        """Re-hear the whole turn with the accurate model before the agent acts on it."""
        from .stt_refine import strip_wake_lead
        t0 = self.clock()
        try:
            heard = (self.refine(first_seen) or "").strip()
        except Exception as ex:
            heard = ""
            self.log(event="refine_error", error=f"{type(ex).__name__}: {ex}")
        if heard:
            heard_wake, rest = self.wake.split(heard)
            better = rest if heard_wake else (strip_wake_lead(heard) if woke else heard)
            if len(better.split()) >= max(1, min(2, len(cmd.split()))):
                self.log(event="refined", fast=cmd, accurate=better, ms=round((self.clock() - t0) * 1000))
                cmd = better
        self.log(event="task", text=cmd)
        self.worker.submit_task(cmd, done=self._task_done)

    def expects_reply(self) -> bool:
        a = self.worker.agent
        if a is None:
            return False
        return bool(getattr(a, "suggestion", "")) or str(getattr(a, "last_said", "")).rstrip().endswith("?")

    def _task_done(self, ok: bool) -> None:
        """After a task, listen without the wake phrase only if the monster asked you
        something; otherwise it's back to "Hey Monster" (no picking up room chatter)."""
        listen = not self.followup_only_on_question or self.expects_reply()
        with self._lock:
            self.armed_until = self.clock() + self.followup_window if listen else 0.0
        self.feedback("ok" if ok else "error")
        if listen:
            self.feedback("followup")

    # ---- firing -------------------------------------------------------
    def _fire_intent(self, ln: _Line, intent: Intent, cmd: str, early: bool) -> None:
        ln.fired = True
        if not self._is_you(ln.first_seen, ln.typed):
            self.feedback("unknown")
            return
        self.armed_until = 0.0
        now = self.clock()
        if intent.name == "exit_app":
            self.worker.cancel()
            self.go_to_sleep(cmd)
            return
        if intent.name in ("confirm_yes", "confirm_no"):
            if self.pending and now < self.pending_until:
                p, self.pending = self.pending, None
                if intent.name == "confirm_yes":
                    self._run(p, cmd, early, ln)
                else:
                    self.feedback("cancelled")
                    self.log(event="cancelled", text=cmd)
            elif intent.name == "confirm_yes" and self._suggestion():   # "yes" to "Want me to save it?"
                s = self._suggestion()
                self.worker.agent.suggestion = ""
                self.feedback("thinking")
                self.log(event="task", text=f"yes: {s}")
                self.worker.submit_task(f"Yes, please do that: {s}", done=self._task_done)
            elif intent.name == "confirm_no":        # "no" / "stop" with nothing pending
                had = self._suggestion()
                if self.worker.agent is not None:
                    self.worker.agent.suggestion = ""
                self.worker.cancel()
                if had:
                    self.say("Okay. What next?")
                    self.armed_until = self.clock() + self.followup_window
                else:
                    self.feedback("cancelled")
                self.log(event="stop", text=cmd)
            return
        self._dispatch(single(intent), cmd, early, ln)

    def _dispatch(self, plan: Plan, cmd: str, early: bool, ln: _Line) -> None:
        if plan.needs_confirm:
            self.pending, self.pending_until = plan, self.clock() + self.confirm_window
            self.say(f"  needs confirmation: {', '.join(plan.confirm_reasons)}. Say 'yes' or 'no'.")
            self.feedback("confirm")
            self.log(event="needs_confirm", text=cmd, steps=[s.name for s in plan.steps],
                     intent=plan.steps[0].name, args=plan.steps[0].args, early=early)
            return
        self._run(plan, cmd, early, ln)

    def _run(self, plan: Plan, cmd: str, early: bool, ln: _Line) -> None:
        first = plan.steps[0]
        self.log(event="dispatched", text=cmd, source=plan.source, early=early,
                 intent=first.name, args=first.args, steps=[s.name for s in plan.steps],
                 ms_from_line_start=round((self.clock() - ln.first_seen) * 1000, 1))
        self.worker.submit(plan, done=lambda ok: self.feedback("ok" if ok else "error"))
