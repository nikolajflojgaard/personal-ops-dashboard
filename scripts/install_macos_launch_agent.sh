#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="$HOME/.openclaw/personal-ops-dashboard"
PLIST="$HOME/Library/LaunchAgents/ai.openclaw.personal-ops-dashboard.plist"
LOG_DIR="$HOME/Library/Logs/openclaw"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
SERVICE_PATH="/opt/homebrew/bin:/opt/homebrew/opt/node@22/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$RUNTIME_ROOT/scripts" "$RUNTIME_ROOT/dashboard"
cp "$ROOT/scripts/personal_ops_dashboard.py" "$RUNTIME_ROOT/scripts/personal_ops_dashboard.py"
cp "$ROOT/ops-dashboard.json" "$RUNTIME_ROOT/ops-dashboard.json"
chmod +x "$RUNTIME_ROOT/scripts/personal_ops_dashboard.py"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>ai.openclaw.personal-ops-dashboard</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>WorkingDirectory</key>
    <string>$RUNTIME_ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>$SERVICE_PATH</string>
    </dict>
    <key>ProgramArguments</key>
    <array>
      <string>$PYTHON_BIN</string>
      <string>$RUNTIME_ROOT/scripts/personal_ops_dashboard.py</string>
      <string>generate</string>
      <string>--config</string>
      <string>$RUNTIME_ROOT/ops-dashboard.json</string>
      <string>--output</string>
      <string>$RUNTIME_ROOT/dashboard</string>
    </array>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/personal-ops-dashboard.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/personal-ops-dashboard.err.log</string>
  </dict>
</plist>
EOF

launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/ai.openclaw.personal-ops-dashboard"

echo "Installed $PLIST"
echo "Dashboard: $RUNTIME_ROOT/dashboard/index.html"
