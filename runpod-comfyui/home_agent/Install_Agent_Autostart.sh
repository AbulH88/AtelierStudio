#!/usr/bin/env bash
# Run once (as your user) to make the home agent start automatically at login,
# so the studio site can always start/stop ComfyUI remotely — Linux side of the
# dual-boot box (see Install_Agent_Autostart.bat for the Windows side).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/atelier-home-agent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Atelier Home Agent
Comment=Lets the studio site start/stop ComfyUI on this machine
Exec=/bin/bash "$SCRIPT_DIR/Start_Agent.sh"
X-GNOME-Autostart-enabled=true
EOF

echo "Installed: $AUTOSTART_DIR/atelier-home-agent.desktop"
echo "The home agent will launch at every graphical login."
echo "To start it now without logging out, just run: $SCRIPT_DIR/Start_Agent.sh"
echo "(To remove later: rm \"$AUTOSTART_DIR/atelier-home-agent.desktop\")"
