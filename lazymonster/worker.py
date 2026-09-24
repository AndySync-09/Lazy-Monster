"""Single worker thread. All actions and agent tasks run here, in order, so COM
objects (Word) live on one apartment thread and nothing interleaves."""
import os
import queue
import threading
import time
from typing import Callable, Optional

from .plans import Plan


def run_plan(executor, plan: Plan, log: Callable[..., None], clock=time.monotonic) -> bool:
    for i, step in enumerate(plan.steps, 1):
        t0 = clock()
        ok, msg, _ = executor.run(step)
        log(event="step", n=i, of=len(plan.steps), intent=step.name, ok=ok, msg=msg,
            exec_ms=round((clock() - t0) * 1000, 1))
        if not ok:
            return False
    return True


class Worker:
    def __init__(self, executor, log: Callable[..., None], synchronous: bool = False, clock=time.monotonic):
        self.ex, self.log, self.sync, self.clock = executor, log, synchronous, clock
        self.agent = None
        self.busy = threading.Event()
        self.q: "queue.Queue" = queue.Queue()
        if not synchronous:
            threading.Thread(target=self._loop, daemon=True, name="lazymonster-worker").start()

    def submit(self, plan: Plan, done: Optional[Callable[[bool], None]] = None) -> None:
        self._put(("plan", plan, done))

    def submit_task(self, task: str, done: Optional[Callable[[bool], None]] = None) -> None:
        self._put(("task", task, done))

    def cancel(self) -> None:
        if self.agent is not None:
            self.agent.cancel.set()

    def _put(self, job):
        if self.sync:
            self._do(*job)
        else:
            self.q.put(job)

    def _do(self, kind, payload, done):
        self.busy.set()
        try:
            if kind == "plan":
                ok = run_plan(self.ex, payload, self.log, self.clock)
            else:
                if self.agent is None:
                    raise RuntimeError("no agent configured")
                ok = self.agent.run(payload)
        except Exception as e:
            self.log(event="task_error", error=f"{type(e).__name__}: {e}")
            ok = False
        finally:
            self.busy.clear()
        if done:
            done(ok)

    def _loop(self):
        if os.name == "nt":
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass
        while True:
            self._do(*self.q.get())
