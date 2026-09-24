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
            ids = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "o5")) and not any(
                x in i for x in ("audio", "realtime", "tts", "transcribe", "image", "search", "embedding"))]
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


class BrainControl:
    def __init__(self, cfg, engine, make_agent: Callable[[object], Agent], on_change: Callable[[], None] = lambda: None):
        self.cfg, self.engine, self.make_agent, self.on_change = cfg, engine, make_agent, on_change

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
    def reload(self) -> Optional[str]:
        """Rebuild the brain from the current settings, live."""
        w = self.engine.worker
        try:
            client = build_client(self.cfg)
        except AgentError as e:
            client, err = None, str(e)
        else:
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
        self.cfg.planner = p
        save_setting("planner", p)
        err = self.reload()
        return f"That didn't work: {err}" if err else "Done. " + self.describe()

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
        setattr(self.cfg, field, model)
        save_setting(field, model)
        if p == self.cfg.planner:
            err = self.reload()
            if err:
                return f"Saved, but it didn't start: {err}"
        return f"{PROVIDERS.get(p, p)} model set to {model}."

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
