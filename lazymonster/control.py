"""Change the brain, model and settings while the monster runs: from the settings
panel, by voice ("switch to Claude", "go big"), or from `monster brain`."""
import os
from typing import Callable, List, Optional

from .agent import Agent, AgentError, build_client
from .config import save_setting
from .secrets import get_key

PROVIDERS = {"openai": "OpenAI", "anthropic": "Claude", "local": "a local model"}
ALIASES = {"claude": "anthropic", "anthropic": "anthropic", "openai": "openai", "open ai": "openai", "gpt": "openai",
           "chatgpt": "openai", "chat gpt": "openai", "local": "local", "ollama": "local", "llama": "local",
           "the local model": "local"}
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "local": "LOCAL_LLM_API_KEY"}
MODEL_FIELD = {"openai": "openai_model", "anthropic": "anthropic_model", "local": "local_model"}


def list_models(cfg, provider: str) -> List[str]:
    """Models your key (or server) can use, newest first where the API says so."""
    import requests
    p = ALIASES.get(provider, provider)
    try:
        if p == "openai":
            r = requests.get(f"{cfg.openai_base_url}/models", timeout=10,
                             headers={"Authorization": f"Bearer {get_key(cfg.openai_api_key_env)}"})
            ids = [m["id"] for m in r.json().get("data", [])]
            ids = [i for i in ids if i.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "gpt-6", "o3", "o4")) and not any(
                x in i for x in ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding",
                                 "instruct", "codex", "moderation", "preview-2024", "chat-latest"))]
            return sorted(ids, reverse=True)
        if p == "anthropic":
            r = requests.get(f"{cfg.anthropic_base_url}/models", timeout=10,
                             headers={"x-api-key": get_key(cfg.anthropic_api_key_env), "anthropic-version": "2023-06-01"})
            return [m["id"] for m in r.json().get("data", [])]
        if p == "local":
            r = requests.get(f"{cfg.local_base_url.rstrip('/')}/models", timeout=5)
            return [m["id"] for m in r.json().get("data", [])]
    except Exception:
        return []
    return []


def set_key(env_name: str, value: str) -> None:
    """Remember an API key for this user (Windows: user environment; macOS: Keychain)."""
    os.environ[env_name] = value
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, env_name, 0, winreg.REG_SZ, value)
    elif os.uname().sysname == "Darwin":
        import subprocess
        from .secrets import KEYCHAIN_SERVICE
        svc = KEYCHAIN_SERVICE.get(env_name, "lazymonster-" + env_name.lower())
        subprocess.run(["security", "add-generic-password", "-U", "-a", os.environ.get("USER", ""), "-s", svc, "-w", value],
                       capture_output=True)


PING = [{"type": "function", "function": {"name": "ping", "description": "Reply to a ping",
                                          "parameters": {"type": "object", "properties": {}}}}]


def can_drive_apps(client, timeout: float = 30.0) -> None:
    """The monster only works with a model that answers and calls tools. Raises with the reason."""
    old = getattr(client, "timeout", None)
    try:
        if old is not None:
            client.timeout = min(old, timeout)
        data = client.chat([{"role": "user", "content": "Call the ping tool now."}], PING)
    except Exception as e:
        if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
            raise AgentError(f"no answer in {int(timeout)} s: the model may still be loading, or the machine is short "
                             "on memory (close other model servers)")
        raise
    finally:
        if old is not None:
            client.timeout = old
    msg = data["choices"][0]["message"]
    if not msg.get("tool_calls"):
        raise AgentError("it answered but didn't use tools, so it can't drive your apps")


class BrainControl:
    def __init__(self, cfg, engine, make_agent: Callable[[object], Agent], on_change: Callable[[], None] = lambda: None):
        self.cfg, self.engine, self.make_agent, self.on_change = cfg, engine, make_agent, on_change
        self.validate = can_drive_apps           # checked before a new brain or model is kept

    # ---- state -------------------------------------------------------------------
    def describe(self) -> str:
        c, p = self.cfg, self.cfg.planner
        if not self.engine.agent_enabled:
            return "I don't have a brain right now, so I can only do quick commands."
        model = getattr(c, MODEL_FIELD.get(p, "openai_model"), "")
        big = self._big_model()
        return (f"I'm using {PROVIDERS.get(p, p)}, {model}."
                + (f" Hard tasks go big on {big}." if c.go_big and big else ""))

    def _big_model(self) -> str:
        c = self.cfg
        return {"openai": c.escalation_model, "anthropic": c.anthropic_escalation_model,
                "local": c.escalation_model if get_key(c.openai_api_key_env) else c.anthropic_escalation_model}.get(c.planner, "")

    def available(self, p: str) -> bool:
        if p == "local":
            return bool(self.cfg.local_base_url)
        return bool(get_key(KEY_ENV[p]))

    # ---- changes -------------------------------------------------------------------
    def reload(self, check: bool = False) -> Optional[str]:
        """Rebuild the brain from the current settings, live. check=True tries it first."""
        w = self.engine.worker
        try:
            client = build_client(self.cfg)
            if check and client is not None:
                self.validate(client)
        except Exception as e:
            return str(e)[:200]
        err = None
        if client is None:
            w.agent, self.engine.agent_enabled = None, False
        else:
            if w.agent is None:
                w.agent = self.make_agent(client)
            w.agent.client = client
            try:
                w.agent.escalation = build_client(self.cfg, escalation=True)
            except Exception:
                w.agent.escalation = None
            self.engine.agent_enabled = True
        self.on_change()
        return err

    def switch(self, to: str) -> str:
        p = ALIASES.get(to.lower().strip(), to.lower().strip())
        if p not in PROVIDERS:
            return f"I don't know a brain called {to}."
        if not self.available(p):
            what = "a local model address" if p == "local" else f"a {PROVIDERS[p]} key"
            return f"I need {what} first. Open settings and add it, then ask me again."
        before = self.cfg.planner
        self.cfg.planner = p
        err = self.reload(check=True)
        if err:
            self.cfg.planner = before                    # keep the brain that works
            return f"{PROVIDERS[p]} didn't work ({err}). I kept {PROVIDERS.get(before, before)}."
        save_setting("planner", p)
        return "Done. " + self.describe()

    def go_big(self, on: bool) -> str:
        self.cfg.go_big = on
        save_setting("go_big", on)
        self.reload()
        big = self._big_model()
        if on and not big:
            return "There's no bigger brain set up for this one. Add a cloud key in settings to go big."
        return f"Going big on hard tasks with {big}." if on else "Back to the normal brain for everything."

    def set_model(self, model: str, provider: str = "") -> str:
        p = ALIASES.get(provider, provider) or self.cfg.planner
        field = MODEL_FIELD.get(p)
        if not field:
            return "Pick a provider first."
        before = getattr(self.cfg, field)
        setattr(self.cfg, field, model)
        if p == self.cfg.planner:
            err = self.reload(check=True)
            if err:
                setattr(self.cfg, field, before)          # keep the model that works
                return f"{model} didn't work ({err}). I kept {before}."
        save_setting(field, model)
        return f"Now using {model}." if p == self.cfg.planner else f"{PROVIDERS.get(p, p)} model set to {model}."

    def test(self) -> str:
        a = self.engine.worker.agent
        if a is None:
            return "No brain to test."
        try:
            a.client.chat([{"role": "user", "content": "Reply with the single word: ready"}])
            return "The brain answered. All good."
        except Exception as e:
            return f"The brain didn't answer: {str(e)[:160]}"

    # ---- voice commands ----------------------------------------------------------------
    def handle(self, name: str, args: dict) -> str:
        if name == "brain_switch":
            return self.switch(args.get("to", ""))
        if name == "brain_big":
            return self.go_big(args.get("on") == "yes")
        return self.describe()
