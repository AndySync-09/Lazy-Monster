#!/usr/bin/env bash
# Lazy-Monster: one-command installer for macOS (Apple Silicon and Intel).
#
#   curl -fsSL https://raw.githubusercontent.com/AndySync-09/lazy-monster/main/install.sh | bash
#
# Installs to ~/.lazymonster (no sudo). Re-run to update; settings, voiceprint and models are kept.
# Optional:  OPENAI_API_KEY=sk-...  LM_SKIP_VOICE=1  LM_ZIP=/path/lazy-monster.zip
set -euo pipefail

REPO="${LM_REPO:-AndySync-09/lazy-monster}"
REF="${LM_REF:-main}"
ROOT="$HOME/.lazymonster"
APP="$ROOT/app"
VENV="$APP/.venv"
PY="$VENV/bin/python"
MONSTER="$VENV/bin/monster"
TTY=/dev/tty

step() { printf "\n\033[32m[%s/6] %s\033[0m\n" "$1" "$2"; }
note() { printf "      %s\n" "$1"; }
die()  { printf "\n\033[31m  %s\033[0m\n" "$1"; exit 1; }

[ "$(uname)" = "Darwin" ] || die "This installer is for macOS. On Windows use install.ps1."
printf "\n\033[35m  Lazy-Monster installer\033[0m\n  Say it. The monster does it.\n"

# 0. Brain first ----------------------------------------------------------------------------
printf "\n\033[32m  Choose the monster's brain\033[0m\n"
note "1  OpenAI (GPT)   2  Claude (Anthropic)   3  None for now (instant commands only)"
BRAIN="${LM_BRAIN:-}"
if [ -z "$BRAIN" ] && [ -r "$TTY" ]; then printf "      Pick 1-3 [1]: "; read -r BRAIN < "$TTY" || BRAIN=""; fi
case "$BRAIN" in 2|claude|anthropic) BRAIN=anthropic ;; 3|none) BRAIN=none ;; *) BRAIN=openai ;; esac
if [ "$BRAIN" != "none" ]; then
  case "$BRAIN" in openai) ENVN=OPENAI_API_KEY; SVC=lazymonster-openai ;; anthropic) ENVN=ANTHROPIC_API_KEY; SVC=lazymonster-anthropic ;; esac
  if security find-generic-password -s "$SVC" >/dev/null 2>&1; then
    note "Found your $ENVN in the Keychain. Keeping it."
  else
    KEY="${!ENVN:-}"
    if [ -z "$KEY" ] && [ -r "$TTY" ]; then printf "      Paste your %s (hidden): " "$ENVN"; read -rs KEY < "$TTY" || KEY=""; echo; fi
    if [ -n "$KEY" ]; then security add-generic-password -U -a "$USER" -s "$SVC" -w "$KEY"; note "Saved in your Keychain."
    else note "No key: instant commands only for now."; BRAIN=none; fi
  fi
fi

DECIDER=""
JEV="${LM_JEV:-}"
note "Optional: Jev by TypeSafe makes fast yes/no and choice calls (ignores room chatter, picks the model)."
if [ -z "$JEV" ] && [ -r "$TTY" ]; then printf "      Add Jev? Needs a TypeSafe API key. [y/N]: "; read -r JEV < "$TTY" || JEV=""; fi
case "$JEV" in [yY]*)
  if ! security find-generic-password -s lazymonster-typesafe >/dev/null 2>&1; then
    JKEY="${TYPESAFE_API_KEY:-}"
    if [ -z "$JKEY" ] && [ -r "$TTY" ]; then printf "      Paste your TYPESAFE_API_KEY (hidden): "; read -rs JKEY < "$TTY" || JKEY=""; echo; fi
    [ -n "$JKEY" ] && security add-generic-password -U -a "$USER" -s lazymonster-typesafe -w "$JKEY"
  fi
  DECIDER=jev ;;
esac

# 1. Python -----------------------------------------------------------------------------
step 1 "Checking for Python 3.11 or newer"
find_python() {
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)
      if [ "$v" -ge 311 ]; then command -v "$c"; return 0; fi
    fi
  done
  return 1
}
BASE="$(find_python || true)"
if [ -z "$BASE" ]; then
  if command -v brew >/dev/null 2>&1; then
    note "Installing Python 3.12 with Homebrew..."
    brew install python@3.12 >/dev/null
    BASE="$(brew --prefix)/bin/python3.12"
  else
    die "Python 3.11+ is needed. Install it from https://www.python.org/downloads/macos/ (or Homebrew), then run this again."
  fi
fi
note "Using $BASE ($(uname -m))"

# 2. Download ---------------------------------------------------------------------------
step 2 "Getting Lazy-Monster"
if [ -x "$PY" ]; then
  note "Stopping the running copy so it can be updated..."
  "$PY" -m lazymonster.cli service stop >/dev/null 2>&1 || true
fi
TMP="$(mktemp -d)"
ZIP="${LM_ZIP:-$TMP/lazy-monster.zip}"
if [ -z "${LM_ZIP:-}" ]; then
  curl -fsSL "https://codeload.github.com/$REPO/zip/refs/heads/$REF" -o "$ZIP"
fi
unzip -q "$ZIP" -d "$TMP/x"
SRC="$(find "$TMP/x" -mindepth 1 -maxdepth 1 -type d | head -n1)"
[ -f "$SRC/pyproject.toml" ] || SRC="$TMP/x"
mkdir -p "$APP"
find "$APP" -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
cp -R "$SRC"/. "$APP"/
rm -rf "$TMP"
note "Installed files in $APP"

# 3. Install ----------------------------------------------------------------------------
step 3 "Installing (its own private Python environment)"
[ -x "$PY" ] || "$BASE" -m venv "$VENV"
"$PY" -m pip install --upgrade pip --quiet --disable-pip-version-check
"$PY" -m pip install "$APP" --quiet --disable-pip-version-check
"$PY" -m pip install --force-reinstall --no-deps "$APP" --quiet --disable-pip-version-check
mkdir -p "$HOME/.local/bin"
ln -sf "$MONSTER" "$HOME/.local/bin/monster"
PROFILE="$HOME/.zprofile"
if ! grep -qs '.local/bin' "$PROFILE"; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"   # Lazy-Monster\n' >> "$PROFILE"
  note "Added 'monster' to your PATH (new terminals)"
fi

# 4. Brain (chosen at the start, saved now) --------------------------------------------------
"$PY" -c "from lazymonster.config import save_setting as s; s('planner', '$BRAIN')"
"$PY" -c "from lazymonster.config import save_setting as s; s('decider', '$DECIDER')"
note "Brain: $BRAIN ${DECIDER:+(+ Jev)}"

# 5. Models, permissions and your voice ------------------------------------------------------
step 5 "Voice models (about 1 GB, one time), permissions and your voice"
"$MONSTER" models --quiet
note "macOS will ask for Microphone, Accessibility and Automation access. Say yes; they are what let it help."
if [ "${LM_SKIP_VOICE:-0}" != "1" ] && [ -r "$TTY" ]; then
  printf "      Open the privacy settings now? [Y/n] "; read -r A < "$TTY" || A=""
  case "$A" in [nN]*) note "Later: monster permissions" ;; *) "$MONSTER" permissions < "$TTY" ;; esac
  printf "      Teach it your voice now? Recommended, about 3 minutes. [Y/n] "; read -r A < "$TTY" || A=""
  case "$A" in
    [nN]*) note "Later: monster wake-train ; monster voice-enroll" ;;
    *) "$MONSTER" wake-train < "$TTY"; "$MONSTER" voice-enroll < "$TTY" ;;
  esac
fi

# 6. Start ------------------------------------------------------------------------------
step 6 "Starting Lazy-Monster at login"
"$MONSTER" service install
printf "\n\033[35m  Done. Say \"Hey Monster\", or press Cmd+Shift+Space.\033[0m\n"
printf "  Update: run the same command. Remove: bash %s/uninstall.sh\n\n" "$APP"
