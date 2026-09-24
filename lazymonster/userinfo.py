"""Who is at the keyboard: the Windows display name, turned into a first name."""
import os
import re
import sys


def first_name(display: str = "", username: str = "") -> str:
    for raw in (display, username):
        raw = (raw or "").strip()
        if not raw:
            continue
        if "\\" in raw:                       # DOMAIN\\user
            raw = raw.split("\\")[-1]
        if "@" in raw:                        # user@outlook.com
            raw = raw.split("@")[0]
        token = re.split(r"[\s._-]+", raw)[0]
        token = re.sub(r"\d+$", "", token)    # andy0 -> andy
        if len(token) >= 2:
            return token[0].upper() + token[1:] if token.islower() else token
    return ""


def windows_first_name(override: str = "") -> str:
    if override:
        return override
    display = ""
    if sys.platform == "darwin":
        try:
            import subprocess
            display = subprocess.run(["id", "-F"], capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:
            display = ""
    if os.name == "nt":
        try:
            import win32api
            display = win32api.GetUserNameEx(3)          # NameDisplay: "Annatam Dey" / "Andy"
        except Exception:
            try:
                import win32net
                display = win32net.NetUserGetInfo(None, os.environ.get("USERNAME", ""), 2).get("full_name", "")
            except Exception:
                display = ""
    return first_name(display, os.environ.get("USERNAME") or os.environ.get("USER", ""))


GREETINGS = ["Hi {name}, how can I help?", "Yes, {name}?", "Hey {name}, what can I do for you?",
             "I'm here, {name}. What do you need?"]
