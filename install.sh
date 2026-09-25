#!/usr/bin/env bash
# Lazy-Monster for Apple Silicon: one-command installer for macOS (the `apple` branch).
#
#   curl -fsSL https://raw.githubusercontent.com/AndySync-09/Lazy-Monster/apple/install.sh | bash
#
# Installs to ~/.lazymonster (no sudo). Re-run to update; settings, voiceprint and models are kept.
# Optional:  OPENAI_API_KEY=sk-...  LM_SKIP_VOICE=1  LM_ZIP=/path/lazy-monster.zip
set -euo pipefail

REPO="${LM_REPO:-AndySync-09/Lazy-Monster}"
REF="${LM_REF:-apple}"
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

# 0. Brain first: no brain, no go ------------------------------------------------------------
printf "\n\033[32m  The monster's brain\033[0m\n"
[ "$(uname -m)" = "arm64" ] || note "This Mac has an Intel chip: it works, but the quick brain and fast speech need Apple Silicon."
BRAIN="${LM_BRAIN:-}"; LOCAL_URL="${LM_LOCAL_URL:-}"; LOCAL_MODEL="${LM_LOCAL_MODEL:-}"; GO_BIG="${LM_GO_BIG:-0}"
have_key() { security find-generic-password -s "$1" >/dev/null 2>&1; }
save_key() { security add-generic-password -U -a "$USER" -s "$1" -w "$2"; }
test_key() {  # $1 openai|anthropic  $2 key
  if [ "$1" = openai ]; then curl -fsS -m 15 https://api.openai.com/v1/models -H "Authorization: Bearer $2" >/dev/null 2>&1
  else curl -fsS -m 15 https://api.anthropic.com/v1/models -H "x-api-key: $2" -H "anthropic-version: 2023-06-01" >/dev/null 2>&1; fi
}
tool_test() {  # $1 url  $2 model: can it call a tool?
  curl -fsS -m 120 "$1/chat/completions" -H "Content-Type: application/json" -d "{\"model\":\"$2\",\"messages\":[{\"role\":\"user\",\"content\":\"Call the ping tool now.\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"ping\",\"description\":\"Reply to a ping\",\"parameters\":{\"type\":\"object\",\"properties\":{}}}}]}" 2>/dev/null | grep -q '"tool_calls"'
}
CURRENT=""
if have_key lazymonster-openai; then CURRENT=openai; elif have_key lazymonster-anthropic; then CURRENT=anthropic; fi
if [ -z "$BRAIN" ] && [ -n "$CURRENT" ] && [ -r "$TTY" ]; then
  note "Monster Brain: $CURRENT (key in your Keychain)"
  note "1  Keep it   2  Switch brain   3  Make the monster go big (hard tasks on a stronger model)"
  printf "      Pick 1-3 [1]: "; read -r K < "$TTY" || K=""
  case "$K" in 2) BRAIN="" ;; 3) BRAIN="$CURRENT"; GO_BIG=1 ;; *) BRAIN="$CURRENT" ;; esac
fi
case "$BRAIN" in claude) BRAIN=anthropic ;; keep) BRAIN="$CURRENT" ;; esac
while [ -z "$BRAIN" ]; do
  note "The monster needs a brain to plan real tasks. Pick one:"
  note "1  OpenAI (GPT)   2  Claude (Anthropic)   3  Local model (Ollama, LM Studio, llama.cpp)   q  Quit"
  [ -r "$TTY" ] || die "Set LM_BRAIN=openai|claude|local to install without questions."
  printf "      Pick 1-3: "; read -r K < "$TTY" || K=""
  case "$K" in
    q) die "No brain, no monster. Run this again when you have a key or a local model." ;;
    1|2)
      if [ "$K" = 1 ]; then KIND=openai; ENVN=OPENAI_API_KEY; else KIND=anthropic; ENVN=ANTHROPIC_API_KEY; fi
      KEY="${!ENVN:-}"
      [ -n "$KEY" ] || { printf "      Paste your %s (hidden): " "$ENVN"; read -rs KEY < "$TTY" || KEY=""; echo; }
      [ -n "$KEY" ] || continue
      if test_key "$KIND" "$KEY"; then save_key "lazymonster-$KIND" "$KEY"; note "Works. Saved in your Keychain."; BRAIN="$KIND"
      else note "That key didn't work (wrong key or offline). Try again."; fi ;;
    3)
      for u in http://localhost:11434/v1 http://localhost:1234/v1 http://localhost:8080/v1; do
        if curl -fsS -m 2 "$u/models" >/dev/null 2>&1; then note "Found a model server at $u"; LOCAL_URL="$u"; break; fi
      done
      [ -n "$LOCAL_URL" ] || { printf "      Endpoint URL (e.g. http://localhost:11434/v1): "; read -r LOCAL_URL < "$TTY"; }
      LOCAL_URL="${LOCAL_URL%/}"
      note "Models there: $(curl -fsS -m 5 "$LOCAL_URL/models" 2>/dev/null | grep -o '"id":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' ')"
      printf "      Which model? "; read -r LOCAL_MODEL < "$TTY"
      if tool_test "$LOCAL_URL" "$LOCAL_MODEL"; then note "It can use tools."; BRAIN=local
      else
        note "It answered without using the tool, so it may fail at actions. Ollama: pick a model with tool support (qwen3, llama3.1)."
        printf "      Use it anyway? [y/N]: "; read -r A < "$TTY" || A=""; case "$A" in [yY]*) BRAIN=local ;; esac
      fi ;;
  esac
  if [ -n "$BRAIN" ] && [ "$GO_BIG" != 1 ] && [ -r "$TTY" ] && [ "$BRAIN" != local ]; then
    printf "      Make the monster go big on hard tasks? Costs more per hard task. [y/N]: "; read -r A < "$TTY" || A=""
    case "$A" in [yY]*) GO_BIG=1 ;; esac
  fi
done
note "Monster Brain: $BRAIN${LOCAL_MODEL:+ ($LOCAL_MODEL)}$( [ "$GO_BIG" = 1 ] && echo ", goes big on hard tasks")"

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
if [ "$BRAIN" = local ]; then "$PY" -c "from lazymonster.config import save_setting as s; s('local_base_url', '$LOCAL_URL'); s('local_model', '$LOCAL_MODEL')"; fi
"$PY" -c "from lazymonster.config import save_setting as s; s('go_big', $( [ "$GO_BIG" = 1 ] && echo True || echo False ))"
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

# 5b. The quick brain on Apple Silicon ---------------------------------------------------------
if [ "$(uname -m)" = "arm64" ] && [ "${LM_SKIP_VOICE:-0}" != "1" ] && [ -r "$TTY" ]; then
  printf "      Set up the quick brain (simple requests on your Mac, offline; about 1 GB)? [Y/n] "; read -r A < "$TTY" || A=""
  case "$A" in [nN]*) note "Later: monster bench-brain --device MLX ; monster brain --quick on" ;;
    *) "$MONSTER" bench-brain --device MLX && "$MONSTER" brain --quick on || note "Skipped: the main brain does everything." ;; esac
fi

# 6. Start ------------------------------------------------------------------------------
step 6 "Starting Lazy-Monster at login"
"$MONSTER" service install
printf "\n\033[35m  Done. Say \"Hey Monster\", or press Cmd+Shift+Space.\033[0m\n"
printf "  Update: run the same command. Remove: bash %s/uninstall.sh\n\n" "$APP"
