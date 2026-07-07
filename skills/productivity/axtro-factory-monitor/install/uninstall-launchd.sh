#!/usr/bin/env bash
# Remove o LaunchAgent do briefing da manhã.
set -euo pipefail
LABEL="com.axtroai.hermes.briefing"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "✅ Removido: $LABEL"
