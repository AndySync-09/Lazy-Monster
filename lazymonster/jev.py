"""Jev (TypeSafe System One): fast, calibrated decisions, not text.

Jev answers typed questions about a state: yes/no probability ("noul"), a choice
with a probability for every option, or a score. It can't write or plan, so it
never replaces the brain (OpenAI or Claude). It makes the quick calls around it:

- Is this speech even meant for the monster?   (no wake word, during a follow-up)
- Which tools fit this request?                  (real probabilities for the decision tree)
- How hard is it?                                (hard tasks start on the stronger model)
- Did the user just agree?                       (spoken yes/no to "Run it now?")

Every call has a short timeout; if Jev is slow or unreachable, the monster
carries on exactly as it would without it.
API: POST {base}/v1/systemone  {state, model, questions} -> {answers}."""
import time
from typing import Dict, Optional


class Jev:
    def __init__(self, api_key_env: str = "TYPESAFE_API_KEY", base_url: str = "https://api.typesafe.ai",
                 model: str = "jev-latest", timeout: float = 2.5, log=None):
        from .secrets import get_key
        self.key = get_key(api_key_env) or get_key("JEV_API_KEY")
        if not self.key:
            raise RuntimeError(f"{api_key_env} is not set")
        self.base_url, self.model, self.timeout = base_url.rstrip("/"), model, timeout
        self.log = log or (lambda **k: None)

    def ask(self, state, questions: Dict[str, dict]) -> Optional[dict]:
        import requests
        t0 = time.perf_counter()
        try:
            r = requests.post(f"{self.base_url}/v1/systemone", timeout=self.timeout,
                              headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
                              json={"state": state, "model": self.model, "questions": questions})
            if r.status_code != 200:
                self.log(event="jev_error", status=r.status_code, text=r.text[:160])
                return None
            answers = r.json().get("answers", {})
            self.log(event="jev", ms=round((time.perf_counter() - t0) * 1000), keys=list(answers))
            return answers
        except Exception as e:
            self.log(event="jev_error", error=type(e).__name__)
            return None

    # ---- the monster's questions ------------------------------------------------------------
    def addressed(self, heard: str, last_said: str = "") -> Optional[float]:
        """Probability the speech is a request or reply to the assistant (not room chatter)."""
        a = self.ask({"assistant_last_said": last_said, "heard": heard},
                     {"addressed": {"type": "noul",
                                    "instructions": "Is `heard` someone talking to the voice assistant: a request, "
                                                    "a command, or a reply to what it last said?",
                                    "criteria": {"true": "Directed at the assistant",
                                                 "false": "Background talk, TV, a phone call, or talking to someone else"}}})
        return None if not a else a.get("addressed", {}).get("noul")

    def agreed(self, question: str, answer: str) -> Optional[float]:
        a = self.ask({"assistant_asked": question, "user_answered": answer},
                     {"yes": {"type": "noul", "instructions": "Did the user agree or give permission?"}})
        return None if not a else a.get("yes", {}).get("noul")

    def plan(self, task: str, tools: Dict[str, str]) -> Optional[dict]:
        """Which tool fits first, and how hard the task is, in one call."""
        options = dict(list(tools.items())[:254])
        options["just_answer"] = "No tool needed: reply in words"
        a = self.ask(task, {
            "tool": {"type": "choice", "instructions": "Which tool should a desktop assistant use first for this request?",
                     "criteria": options},
            "difficulty": {"type": "score", "instructions": "How hard is this request for an AI assistant?",
                           "criteria": ["One simple step", "A few straightforward steps",
                                        "Many steps, writing code or a long document"]}})
        if not a or "tool" not in a:
            return None
        probs = a["tool"].get("probabilities", {})
        top = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
        return {"candidates": [{"tool": t, "p": round(p, 2)} for t, p in top],
                "difficulty": a.get("difficulty", {}).get("score")}


def build_jev(cfg, log=None) -> Optional[Jev]:
    if (cfg.decider or "").lower() != "jev":
        return None
    try:
        return Jev(cfg.jev_api_key_env, cfg.jev_base_url, cfg.jev_model, cfg.jev_timeout, log)
    except Exception:
        return None
