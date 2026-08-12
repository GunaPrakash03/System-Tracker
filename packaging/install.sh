#!/usr/bin/env bash
#
# System-Tracker installer (Linux / GNOME).
#
# Installs, for the CURRENT user:
#   * the process/screenshot tracker            -> ~/.local/share/system-tracker/
#   * the silent-screenshot GNOME extension     -> ~/.local/share/gnome-shell/extensions/
#   * a systemd user service (auto-start, keeps running)
#
# Stdlib-only Python — no pip. Run as your normal user (NOT root/sudo):
#   ./install.sh
#
# Credentials: set them in the environment, or edit the config after install.
#   GAUZY_URL=http://host:3000 GAUZY_EMAIL=you@co GAUZY_PASSWORD=... ./install.sh
set -euo pipefail

APP_DIR="$HOME/.local/share/system-tracker"
EXT_UUID="system-tracker-shot@local"
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
UNIT_DIR="$HOME/.config/systemd/user"
# Where the files to install are, which is NOT the same place in both layouts:
# in the repo this script lives in packaging/ and the sources are one level up,
# but build-bundle.sh puts it at the top of the archive with tracker/ as a
# sibling. Resolving to the parent unconditionally sent a bundle install looking
# outside the extracted folder — for ~/tracker/proc_tracker.py rather than
# ~/system-tracker/tracker/proc_tracker.py — and set -e aborted on the first cp.
# Probe for tracker/ instead of assuming either shape.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$HERE/tracker" ]; then
    SRC="$HERE"                                  # extracted bundle
else
    SRC="$(cd "$HERE/.." && pwd)"                # repo checkout
fi

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user, not root."; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required."; exit 1; }
python3 -c 'import gi' 2>/dev/null || warn "python3-gi not found — screenshots will be disabled until you install it (apt install python3-gi)."

# 1. Tracker files
say "Installing tracker to $APP_DIR"
mkdir -p "$APP_DIR"
cp "$SRC/tracker/proc_tracker.py" "$SRC/tracker/report.py" "$APP_DIR/"

# 2. Config
if [ ! -f "$APP_DIR/config.json" ]; then
    cp "$SRC/tracker/config.example.json" "$APP_DIR/config.json"
    # 0600 BEFORE anything is written into it. This file holds the Gauzy
    # password in plaintext, and the default umask leaves it world-readable —
    # on a shared workstation any local user could read the credentials the
    # tracker posts everyone's activity with.
    chmod 600 "$APP_DIR/config.json"
    if [ -n "${GAUZY_URL:-}" ] || [ -n "${GAUZY_EMAIL:-}" ] || [ -n "${GAUZY_PASSWORD:-}" ]; then
        python3 - "$APP_DIR/config.json" <<'PY'
import json, os, sys
p = sys.argv[1]; c = json.load(open(p))
for k, e in (("server_url","GAUZY_URL"),("email","GAUZY_EMAIL"),("password","GAUZY_PASSWORD")):
    if os.environ.get(e): c[k] = os.environ[e]
json.dump(c, open(p,"w"), indent=2)
PY
        say "Config seeded from environment."
    else
        warn "Edit $APP_DIR/config.json — set server_url / email / password."
    fi
fi

# 3. GNOME extension (silent screenshots)
if [ -d "$SRC/tracker/gnome-extension/$EXT_UUID" ]; then
    say "Installing GNOME extension $EXT_UUID"
    mkdir -p "$EXT_DIR"
    cp "$SRC/tracker/gnome-extension/$EXT_UUID/"* "$EXT_DIR/"
    gnome-extensions enable "$EXT_UUID" 2>/dev/null && say "Extension enabled." \
        || warn "Could not enable now — log out/in once, then: gnome-extensions enable $EXT_UUID"
fi

# 4. systemd user service
say "Installing systemd user service"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/system-tracker.service" <<EOF
[Unit]
Description=System-Tracker process + screenshot tracker
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 $APP_DIR/proc_tracker.py $APP_DIR/config.json
Restart=always
RestartSec=5

[Install]
WantedBy=graphical-session.target
EOF
systemctl --user daemon-reload
# `enable --now` starts a stopped service but does NOTHING to a running one, so
# re-running this script to upgrade an existing install would copy the new code
# and leave the old code running — with a log that looks entirely healthy.
# Enable for next login, then restart unconditionally: restart also starts a
# service that is not running, so this covers a first install too.
systemctl --user enable system-tracker.service 2>/dev/null || true
systemctl --user restart system-tracker.service 2>/dev/null \
    && say "Service started." || warn "Start manually: systemctl --user restart system-tracker.service"

echo
say "Done. Next:"
echo "   • If the extension didn't enable, LOG OUT and back in once."
echo "   • Check it:   systemctl --user status system-tracker"
echo "   • Logs:       journalctl --user -u system-tracker -f"
echo "   • Config:     $APP_DIR/config.json"
