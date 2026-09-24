"""The agent loop: model sees the task, calls typed tools one at a time, sees
each result, and finishes. Works with any Chat Completions compatible API.

Safety: every tool call is validated against intents.SCHEMA; invalid or guarded
calls return an error to the model instead of running. Tools that need a
spoken confirmation (sleep/shutdown/restart) are not offered to the agent at all."""
import json
import os
import queue
import re
import threading
import time
from typing import Callable, Optional

from .intents import AGENT_TOOLS, SCHEMA, SchemaError, validate

SYSTEM = """You are Lazy-Monster, a friendly, sharp voice agent that operates the user's Windows PC on their behalf.
Everything you say is spoken aloud, like a helpful friend in the room: short, natural sentences, no file paths,
no markdown, no em dashes, no lists. One idea per sentence. Never repeat what the user just said back to them.
This is a conversation: remember what was said earlier, and treat short replies ("snake", "the blue one", "yes")
as answers to your last question.
Work step by step with the tools. After opening an app, use list_windows / read_window to see what is on screen before clicking or typing.
Guidelines:
- Before every tool call, put one line of JSON in your message listing the 2-3 actions you considered and your confidence in each, e.g. {"candidates":[{"tool":"write_in_app","p":0.8},{"tool":"open_app","p":0.15},{"tool":"ask_user","p":0.05}]}. The first matching tool you call is your choice.
- Writing in Notepad or another text app: use write_in_app (one step: opens, new document, pastes, verifies).
- Every write reports whether it was verified. If it says MISMATCH, fix it before finishing. To see or rewrite what is already there, use read_text.
- Documents in Word: word_new_document, then word_insert_text with the full text you wrote, then word_save.
- Code: code_open(project), then code_write_file for each file with complete, working code. Never type code with type_text.
- To run Python you wrote, use code_run (never a terminal). If it reports a missing package, use code_install, then code_run again. Both ask the user themselves; do not ask separately first.
- Web: open_url or search_web.
- Other apps: open_app, focus_window, read_window, click, type_text, press_keys.
- Some actions are blocked for safety (terminals, deleting, sending, paying, installing). If blocked, do not retry another way; finish and tell the user what they need to do.
- Keep going until the task is complete (usually within 3-6 steps), then call finish with a one-sentence summary and, in next, the single most useful follow-up you could do for them (save it, format it, run it, send it to a file, open it...), phrased as a short question.
- Act first. Pick sensible defaults (3 slides, a clean design, save in the LazyMonster folder) and say what you chose.
  Ask at most one question per task, and only when a wrong guess would waste real work. Never ask permission for
  harmless steps. If you are truly blocked, ask one specific question.
- To show a file you made (web page, PDF, deck, document), use open_file with its path; add app='chrome' or 'edge'
  if the user named a browser. Never type file paths into address bars or File Explorer.
- PDFs from Word: export_pdf. Presentations: make_presentation with a full outline (never type into PowerPoint).
- Research, news or facts: web_research, then tell the user the answer briefly and mention it came from the web.
- If the user wants you to stop, rest or go to sleep: go_to_sleep.
- If open_app lands on an existing document, press ctrl+n for a new one before typing. Never edit documents the user did not mention.
- Be efficient: open_app already reports the focused window; type or click straight away when it is the right one. Use read_window only when you need to see controls.
- Follow-ups like "save it" or "make it longer" refer to what you just did in this conversation.
- "Close everything" / "clean up" / "I'm done": use close_all (it handles unsaved work and tells you what it saved where; repeat that to the user).
- "What did we work on?" or anything about earlier sessions: use recent_work.
- To close an app use close_app. If a dialog appears (for example "Do you want to save changes?"), read_window to see its buttons. If the user already said what to do, click that; otherwise call ask_user. Never guess on choices that lose work.
- Messages marked "(said while you were working)" are the user talking to you mid-task: follow them.
- Saving through an app's Save dialog: save into the Documents\\LazyMonster folder unless the user names another place."""

MAX_RESULT = 4000


def tool_specs() -> list:
    specs = []
    for n in AGENT_TOOLS:
        s = SCHEMA[n]
        props, req = {}, []
        for k, (typ, lo, hi) in s["slots"].items():
            if typ is int:
                props[k] = {"type": "integer", "minimum": lo, "maximum": hi}
            else:
                props[k] = {"type": "string", "maxLength": hi}
            if k not in s.get("optional", []):
                req.append(k)
        specs.append({"type": "function", "function": {
            "name": n, "description": s.get("desc", n),
            "parameters": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}})
    return specs


class AgentError(RuntimeError):
    pass


class ChatClient:
    """Minimal OpenAI-compatible Chat Completions client."""

    def __init__(self, model: str, api_key_env: str = "OPENAI_API_KEY", base_url: str = "https://api.openai.com/v1",
                 timeout: float = 90.0, reasoning_effort: str = ""):
        self.model, self.base_url, self.timeout, self.reasoning_effort = model, base_url.rstrip("/"), timeout, reasoning_effort
        from .secrets import get_key
        self.key = get_key(api_key_env)
        if not self.key:
            raise AgentError(f"{api_key_env} is not set")

    def chat(self, messages, tools=None) -> dict:
        import requests
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        r = requests.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout,
                          headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code == 400 and self.reasoning_effort and "reasoning" in r.text.lower():
            self.reasoning_effort = ""                # model doesn't take it: drop and retry once
            return self.chat(messages, tools)
        if r.status_code != 200:
            raise AgentError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()


def _responses_text(data: dict) -> tuple:
    """(text, [(title, url), ...]) from an OpenAI Responses API result."""
    text, sources = [], []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for c in item.get("content", []) or []:
            if c.get("type") in ("output_text", "text"):
                text.append(c.get("text", ""))
                for an in c.get("annotations", []) or []:
                    if an.get("type") == "url_citation" and an.get("url"):
                        sources.append((an.get("title") or an["url"], an["url"]))
    return "\n".join(t for t in text if t).strip(), list(dict.fromkeys(sources))


def _finish_json(text: str):
    t = (text or "").strip()
    if not (t.startswith("{") and '"summary"' in t):
        return None
    try:
        d = json.loads(t)
        return d if isinstance(d, dict) and "summary" in d else None
    except ValueError:
        return None


def research(client, question: str) -> str:
    """Real web search (OpenAI hosted web search tool), with sources."""
    import requests
    body = {"model": client.model, "input": f"Research this and answer in 5-8 plain sentences with the key facts and "
                                            f"dates. Question: {question}"}
    last = ""
    for tool in ("web_search", "web_search_preview"):
        body["tools"] = [{"type": tool}]
        r = requests.post(f"{client.base_url}/responses", json=body, timeout=client.timeout,
                          headers={"Authorization": f"Bearer {client.key}"})
        if r.status_code == 200:
            text, src = _responses_text(r.json())
            refs = "\n".join(f"- {t}: {u}" for t, u in src[:6])
            return (text or "(no answer)") + (f"\nSources:\n{refs}" if refs else "\n(no sources returned)")
        last = f"HTTP {r.status_code}: {r.text[:200]}"
    raise AgentError(f"web research unavailable ({last})")


class Agent:
    def __init__(self, client, executor, log: Callable[..., None], say: Callable[[str], None],
                 max_steps: int = 30, clock=time.monotonic, session_timeout: float = 180.0, max_history: int = 60):
        self.client, self.ex, self.log, self._say = client, executor, log, say
        self.last_said = ""
        self.max_steps, self.clock = max_steps, clock
        self.session_timeout, self.max_history = session_timeout, max_history
        self.cancel = threading.Event()
        self.tools = tool_specs()
        self.history: list = []
        self.last_done = -1e9
        self.inbox: "queue.Queue[str]" = queue.Queue()   # speech heard while working
        self.ask_timeout = 25.0
        self.suggestion = ""
        self.on_progress = None
        self.journal = False                      # cli turns this on; tests stay off the disk
        self.on_sleep = None                      # cli: engine.go_to_sleep
        self.escalation = None                    # optional stronger client (e.g. GPT-6 Astra) for hard tasks
        self.step_budget = 8                      # after this, wrap up instead of wandering
        self.max_questions = 2                    # per task
        self.approved = {}                        # (tool, project) -> time: say yes once per project per session

    def _system(self) -> str:
        if not self.journal:
            return SYSTEM
        from . import journal
        ctx = journal.context()
        return SYSTEM + ("\n\n" + ctx if ctx else "")

    def _start_messages(self, task: str) -> list:
        """Follow-ups ("save it", "make it longer") continue the same session."""
        if self.history and self.clock() - self.last_done < self.session_timeout:
            hist = self.history[-self.max_history:]
            while hist and hist[0].get("role") == "tool":      # never start on an orphan tool result
                hist = hist[1:]
            return [{"role": "system", "content": self._system()}] + hist + [{"role": "user", "content": task}]
        return [{"role": "system", "content": self._system()}, {"role": "user", "content": task}]

    def seed(self, assistant_text: str) -> None:
        """Start a conversation with something the monster said (e.g. the welcome-back recap)."""
        self.history = [{"role": "assistant", "content": assistant_text}]
        self.last_done = self.clock()

    def _record(self, task: str, summary: str, results: list) -> None:
        if not self.journal:
            return
        try:
            from . import journal
            journal.add(task, summary, journal.files_in(results))
        except Exception:
            pass

    def _close_all(self) -> str:
        """Close what the monster opened. Unsaved work: ask. A name/place you give wins;
        "yes" or no answer saves to the default folder with a suggested name; "no" discards."""
        from .savepaths import allowed, interpret, unique
        items = self.ex.owned_items()
        if not items:
            return "Nothing I opened is still open."
        default_dir = getattr(self.ex, "default_save_dir", "C:\\temp")
        report = []
        for o in items:
            if o.get("dirty"):
                ans = self._listen(f"{o['label']} has unsaved changes. Should I save it? "
                                   f"Tell me a name or a place, or say no.")
                action, target = interpret(ans or "", o.get("suggest", "note.txt"), default_dir)
                if action == "save":
                    if target is None or not allowed(target.parent, default_dir):
                        from pathlib import Path
                        target = Path(default_dir) / o.get("suggest", "note.txt")
                    if not target.suffix:
                        target = target.with_suffix(o.get("suggest", ".txt")[o.get("suggest", ".txt").rfind("."):])
                    try:
                        saved = self.ex.save_item(o, unique(target))
                        report.append(f"saved {o['label']} to {saved}")
                    except Exception as e:
                        report.append(f"could not save {o['label']} ({e}); left it open")
                        continue
                else:
                    report.append(f"discarded changes in {o['label']}")
            try:
                report.append(self.ex.close_item(o))
            except Exception as e:
                report.append(f"could not close {o['label']} ({type(e).__name__})")
        self.log(event="closed_all", report=report)
        return "; ".join(report)

    def _end(self, messages: list) -> None:
        self.history = messages[1:]
        self.last_done = self.clock()

    def say(self, text: str) -> None:
        self.last_said = text
        self._say(text)

    def hear(self, text: str) -> None:
        """Speech that arrives while a task is running goes to the agent."""
        self.inbox.put(text)

    def _drain(self, messages: list) -> None:
        while True:
            try:
                text = self.inbox.get_nowait()
            except queue.Empty:
                return
            messages.append({"role": "user", "content": f"(said while you were working) {text}"})
            self.log(event="heard_during_task", text=text)

    def _ask(self, question: str) -> str:
        answer = self._listen(question)
        if answer is None:
            return "No answer from the user. Do not guess; finish and say what is waiting on them."
        return f"The user answered: {answer}"

    def _listen(self, question: str):
        self.say(question)
        self.log(event="asking", text=question)
        try:
            return self.inbox.get(timeout=self.ask_timeout)
        except queue.Empty:
            return None

    # Tools that run code or install packages: the user must say yes, decided here, not by the model.
    ASK_FIRST = {"code_run": "Run {path} from {project} now?",
                 "code_install": "Install {packages} into the {project} project's own environment?"}
    _YES = re.compile(r"^\W*(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|run it|install it|please do|confirm)\b", re.I)

    def _approved(self, intent) -> tuple:
        key = (intent.name, intent.args.get("project", ""))
        if self.clock() - self.approved.get(key, -1e9) < 1800:
            return True, "already approved for this project in this session"
        q = self.ASK_FIRST[intent.name].format(**intent.args)
        ans = self._listen(q)
        ok = bool(ans and self._YES.match(ans))
        if ok:
            self.approved[key] = self.clock()
        self.log(event="approval", intent=intent.name, ok=ok, text=ans or "")
        return ok, ("the user said yes" if ok else f"the user did not approve ({ans or 'no answer'}); do not retry")

    def run(self, task: str) -> bool:
        self.cancel.clear()
        results = []
        client = self.client
        questions = 0
        first_action = None
        escalated = False
        while not self.inbox.empty():                  # stale speech from before this task
            self.inbox.get_nowait()
        messages = self._start_messages(task)
        self.suggestion = ""
        fails = 0
        narrated = False
        t_start = self.clock()
        for step in range(1, self.max_steps + 1):
            if self.cancel.is_set():
                self.say("Stopped.")
                self.log(event="agent_cancelled", step=step)
                return False
            self._drain(messages)
            self.ex.context = " ".join(m["content"] for m in messages
                                       if m.get("role") == "user" and isinstance(m.get("content"), str))
            if step == self.step_budget + 1:
                messages.append({"role": "system", "content": "You have used your step budget. Finish now with what "
                                 "you have, or ask the user one specific question. Do not keep exploring."})
            if self.escalation is not None and not escalated and (fails >= 2 or step > 6):
                client, escalated = self.escalation, True          # hard task: hand over to the stronger model
                self.log(event="escalated", model=getattr(client, "model", "?"), step=step)
            t0 = self.clock()
            try:
                data = client.chat(messages, self.tools)
            except AgentError:
                if client is self.client:
                    raise
                client = self.client                               # stronger model unavailable: carry on
                data = client.chat(messages, self.tools)
            try:
                msg = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                raise AgentError("model returned no message")
            calls = msg.get("tool_calls") or []
            from .textops import parse_candidates
            self.log(event="agent_think", step=step, ms=round((self.clock() - t0) * 1000),
                     candidates=parse_candidates(msg.get("content")),
                     chosen=[c.get("function", {}).get("name") for c in calls])
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            if not calls:
                self.log(event="agent_done", steps=step, s=round(self.clock() - t_start, 1),
                         first_action_s=first_action)
                if msg.get("content"):
                    from .textops import CANDIDATES
                    spoken = CANDIDATES.sub("", msg["content"]).strip()
                    fin = _finish_json(spoken)            # model wrote finish's arguments as text
                    if fin:
                        self.suggestion = fin.get("next", "") or ""
                        spoken = f"{fin.get('summary', '')} {self.suggestion}".strip()
                    if spoken:
                        self.say(spoken)
                self._end(messages)
                return True
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name")
                try:
                    if name not in AGENT_TOOLS:
                        raise SchemaError(f"tool {name!r} is not available to the agent")
                    args = json.loads(fn.get("arguments") or "{}")
                    intent = validate(name, args, source="agent", allow_refs=False)
                except Exception as e:                  # bad call never kills the task
                    result = f"ERROR: {type(e).__name__}: {e}"
                    self.log(event="step", n=step, of=self.max_steps, intent=str(name), ok=False, msg=result, exec_ms=0)
                else:
                    if intent.name == "finish":
                        self.suggestion = (intent.args.get("next") or "").strip()
                        summary = intent.args.get("summary") or "Done."
                        self.log(event="agent_done", steps=step, s=round(self.clock() - t_start, 1))
                        self._record(task, summary, results)
                        self.say(f"{summary} {self.suggestion}".strip())      # no reflexive "What next?"
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": "finished"})
                        self._end(messages)
                        return True
                    if intent.name == "ask_user":
                        questions += 1
                        if questions > self.max_questions:
                            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                             "content": "Do not ask again. Proceed with the most sensible default and "
                                                        "tell the user what you chose."})
                            continue
                        answer = self._ask(intent.args["question"])
                        self.log(event="step", n=step, of=self.max_steps, intent="ask_user", ok=True,
                                 msg=answer, exec_ms=0)
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": answer})
                        continue
                    if intent.name == "go_to_sleep":
                        self.log(event="agent_done", steps=step, s=round(self.clock() - t_start, 1))
                        if self.on_sleep:
                            self.on_sleep()
                        return True
                    if intent.name in ("close_all", "recent_work", "web_research"):
                        if intent.name == "close_all":
                            out = self._close_all()
                        elif intent.name == "web_research":
                            try:
                                out = research(client if hasattr(client, "base_url") else self.client,
                                               intent.args["question"])
                            except Exception as e:
                                out = f"ERROR: {e}"
                        else:
                            from . import journal
                            out = journal.context() or "No earlier work in the last week."
                        results.append(out)
                        self.log(event="step", n=step, of=self.max_steps, intent=intent.name, ok=True,
                                 msg=out[:160], exec_ms=0)
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": out[:MAX_RESULT]})
                        continue
                    if intent.name in self.ASK_FIRST:
                        approved, why = self._approved(intent)
                        if not approved:
                            self.log(event="step", n=step, of=self.max_steps, intent=intent.name, ok=False,
                                     msg=why, exec_ms=0)
                            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": why})
                            continue
                    if not narrated and self.on_progress and self.clock() - t_start > 10:
                        narrated = True                   # one short update on long tasks, never a play-by-play
                        self.on_progress(intent.name)
                    t1 = self.clock()
                    if first_action is None:
                        first_action = round(t1 - t_start, 1)
                    ok, text, out = self.ex.run(intent)
                    result = (text if ok else f"ERROR: {text}")
                    results.append(result)
                    fails = 0 if ok else fails + 1
                    if fails >= 2:
                        result += "\n(Two failures in a row: stop retrying and call ask_user with what you need.)"
                    if ok and isinstance(out, str) and out != text:
                        result = out
                    self.log(event="step", n=step, of=self.max_steps, intent=intent.name, ok=ok,
                             msg=_short(intent.args, text), exec_ms=round((self.clock() - t1) * 1000, 1))
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result[:MAX_RESULT]})
                if self.cancel.is_set():
                    break
        self.say("I hit the step limit before finishing.")
        self._end(messages)
        return False


def _short(args: dict, text: str) -> str:
    a = {k: (v[:50] + "…" if isinstance(v, str) and len(v) > 50 else v) for k, v in args.items()}
    first = (text or "").splitlines()[0][:120] if text else ""
    return f"{a} -> {first}"


class JevClient:
    """Placeholder for the Jev Engineering API. Implement chat() to return the
    same shape as ChatClient.chat() (choices[0].message with optional tool_calls)."""

    def __init__(self, url: str, api_key_env: str = "JEV_API_KEY", timeout: float = 60.0):
        self.url, self.timeout, self.key = url, timeout, os.environ.get(api_key_env, "")

    def chat(self, messages, tools=None) -> dict:
        raise AgentError("Jev client is a placeholder: implement JevClient.chat() against the Jev API")


def build_client(cfg):
    p = cfg.planner.lower()
    if p == "openai":
        return ChatClient(cfg.openai_model, cfg.openai_api_key_env, cfg.openai_base_url,
                          cfg.openai_timeout, cfg.openai_reasoning_effort)
    if p == "jev":
        return JevClient(cfg.jev_url, cfg.jev_api_key_env, cfg.jev_timeout)
    return None
