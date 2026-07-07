#!/usr/bin/env bash
# Instala o briefing da manhã como LaunchAgent do macOS (roda todo dia 07:00).
# Fuso: usa o horário local do Mac. Este Mac está em America/New_York (Flórida),
# que é o fuso oficial do Hermes — então 07:00 aqui = 07:00 na Flórida.
#
# Uso:
#   bash install-launchd.sh          # instala/atualiza e carrega
#   bash install-launchd.sh --hour 8 # horário custom
set -euo pipefail

HOUR=7
MINUTE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hour) HOUR="$2"; shift 2 ;;
    --minute) MINUTE="$2"; shift 2 ;;
    *) echo "arg desconhecido: $1"; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
BRIEFING="$SKILL_DIR/scripts/briefing.py"
PYTHON="$(command -v python3)"
LABEL="com.axtroai.hermes.briefing"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/axtro-hermes"
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

if [[ ! -f "$BRIEFING" ]]; then
  echo "ERRO: não achei $BRIEFING"; exit 1
fi

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$BRIEFING</string>
        <string>--llm</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>$HOUR</integer>
        <key>Minute</key><integer>$MINUTE</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/briefing.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/briefing.err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

# Recarrega (bootout ignora erro se ainda não estava carregado)
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "✅ Instalado: $LABEL"
echo "   Horário: $(printf '%02d:%02d' "$HOUR" "$MINUTE") (America/New_York)"
echo "   Script:  $BRIEFING --llm"
echo "   Logs:    $LOG_DIR/"
echo ""
echo "Testar agora sem esperar as 7h:"
echo "   launchctl kickstart gui/$(id -u)/$LABEL"
