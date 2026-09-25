#!/usr/bin/env bash
# Removes Lazy-Monster for this user on macOS:  bash ~/.lazymonster/app/uninstall.sh
ROOT="$HOME/.lazymonster"; APP="$ROOT/app"
[ -x "$APP/.venv/bin/python" ] && "$APP/.venv/bin/python" -m lazymonster.cli service uninstall || true
rm -f "$HOME/.local/bin/monster"
rm -rf "$HOME/Applications/Lazy-Monster.app"
tccutil reset All space.lazymonster.app >/dev/null 2>&1 || true
rm -rf "$APP"
printf "Also delete your settings, voiceprint, journal, models and saved key? [y/N] "; read -r A < /dev/tty || A=""
case "$A" in
  [yY]*) rm -rf "$ROOT" "$HOME/.config/lazymonster" "$HOME/.cache/lazymonster"
         security delete-generic-password -s lazymonster-openai >/dev/null 2>&1 || true ;;
esac
echo "Lazy-Monster removed. Files in ~/Documents/LazyMonster were not touched."
