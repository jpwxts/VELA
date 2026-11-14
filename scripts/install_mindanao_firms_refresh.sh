#!/usr/bin/env bash
# Install the 4-hour Mindanao FIRMS refresh as a user launchd agent.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/scripts/com.vela.mindanao-firms-refresh.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.vela.mindanao-firms-refresh.plist"
mkdir -p "$HOME/Library/LaunchAgents"
sed "s|/Users/florlyn/Desktop/MODISVIIRS|$ROOT|g; s|/Users/florlyn/anaconda3/envs/vela/bin/python|$(command -v python || echo python)|g" \
  "$PLIST_SRC" > "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "Loaded $PLIST_DST"
echo "Or run once: python -m scripts.refresh_mindanao_firms --once"
echo "Or loop:     python -m scripts.refresh_mindanao_firms --loop --interval-minutes 240"
