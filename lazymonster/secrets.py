"""API keys: environment variable first; on macOS also the login Keychain
(the installer stores the key there, so the background agent can read it)."""
import os
import subprocess

from .platform_info import IS_MAC

KEYCHAIN_SERVICE = {"OPENAI_API_KEY": "lazymonster-openai", "ANTHROPIC_API_KEY": "lazymonster-anthropic",
                    "TYPESAFE_API_KEY": "lazymonster-typesafe", "JEV_API_KEY": "lazymonster-typesafe"}


def get_key(env_name: str) -> str:
    v = os.environ.get(env_name, "")
    if v or not IS_MAC:
        return v
    svc = KEYCHAIN_SERVICE.get(env_name, "lazymonster-" + env_name.lower())
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", svc, "-w"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
