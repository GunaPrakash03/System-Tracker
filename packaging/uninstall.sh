#!/usr/bin/env bash
# Remove System-Tracker for the current user (tracker, extension, service).
set -euo pipefail
EXT_UUID="system-tracker-shot@local"

systemctl --user disable --now system-tracker.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/system-tracker.service"
systemctl --user daemon-reload 2>/dev/null || true

gnome-extensions disable "$EXT_UUID" 2>/dev/null || true
rm -rf "$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"

rm -rf "$HOME/.local/share/system-tracker"
echo "System-Tracker removed. (Log out/in to fully unload the GNOME extension.)"
