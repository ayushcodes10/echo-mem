#!/usr/bin/env bash
# Keep the memory dashboard running at http://127.0.0.1:8787, always.
#
# The dashboard is only useful if looking at it is free. Having to remember a
# command, an env block and a venv path is enough friction that you don't
# glance at it, and a graph you don't glance at may as well not exist. This
# installs a user LaunchAgent so the page is just a bookmark.
#
# Localhost only, same as the server itself: that page is every fact you have
# ever recorded across every project.
#
# Uninstall:  launchctl bootout gui/$(id -u)/com.echomem.dashboard
#             rm ~/Library/LaunchAgents/com.echomem.dashboard.plist

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.echomem.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${ECHO_MEMORY_DASHBOARD_PORT:-8787}"

[ "$(uname)" = "Darwin" ] || { echo "launchd is macOS-only; on Linux use a systemd --user unit." >&2; exit 1; }
[ -x "$REPO/.venv/bin/echo-memory" ] || { echo "no venv at $REPO/.venv - run pip install -e '.[dev]' first" >&2; exit 1; }
[ -f "$REPO/.env" ] || { echo "no $REPO/.env - the service needs ECHO_MEMORY_* vars" >&2; exit 1; }

# shellcheck disable=SC1091
set -a; . "$REPO/.env"; set +a

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/echo-memory</string>
    <string>dashboard</string><string>--serve</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ECHO_MEMORY_USER_ID</key><string>${ECHO_MEMORY_USER_ID}</string>
    <key>ECHO_MEMORY_AGENT_ID</key><string>${ECHO_MEMORY_AGENT_ID}</string>
    <key>ECHO_MEMORY_DATABASE_URL</key><string>${ECHO_MEMORY_DATABASE_URL}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key>
  <!-- Restart on crash, but not on a clean exit: if Postgres is down the
       server exits and relaunching in a tight loop just burns CPU. -->
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/$LABEL.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/$LABEL.log</string>
</dict></plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2

if curl -fsS -m 5 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "Dashboard running at http://127.0.0.1:$PORT (starts on login)"
else
  echo "Installed, but not answering yet. Is Postgres up? docker compose up -d" >&2
  echo "Log: ~/Library/Logs/$LABEL.log" >&2
fi
