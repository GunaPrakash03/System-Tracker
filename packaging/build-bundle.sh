#!/usr/bin/env bash
#
# Build a single distributable archive of System-Tracker for Linux/GNOME.
# Produces  dist/system-tracker-<date>.tar.gz  containing everything plus the
# installer — copy that ONE file to another machine, extract, run ./install.sh.
#
#   ./packaging/build-bundle.sh
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="${1:-manual}"                     # pass a version/date; Date.now not used here
OUT="$SRC/dist"
STAGE="$(mktemp -d)/system-tracker"

mkdir -p "$STAGE/tracker" "$OUT"
cp "$SRC/tracker/proc_tracker.py" "$SRC/tracker/report.py" \
   "$SRC/tracker/config.example.json" "$SRC/tracker/README.md" "$STAGE/tracker/"
cp -r "$SRC/tracker/gnome-extension" "$STAGE/tracker/"
cp "$SRC/packaging/install.sh" "$SRC/packaging/uninstall.sh" "$STAGE/"
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh"

TARBALL="$OUT/system-tracker-$STAMP.tar.gz"
tar -czf "$TARBALL" -C "$(dirname "$STAGE")" system-tracker
rm -rf "$(dirname "$STAGE")"
echo "Built: $TARBALL"
echo "Install on another Linux/GNOME box:"
echo "   tar xzf $(basename "$TARBALL") && cd system-tracker && ./install.sh"
