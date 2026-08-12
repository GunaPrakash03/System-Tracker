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
# Archive the CONTENTS, not the staging directory, so extracting drops
# install.sh, uninstall.sh and tracker/ straight into the current directory
# instead of nesting them under system-tracker/. The install is meant to be run
# from the operator's home directory, and a wrapper folder there is just a step
# to remember and a place to forget things in. install.sh probes for tracker/
# beside itself, so it resolves correctly either way.
#
# Extract into an empty-ish directory: without a single root, tar will happily
# scatter three entries into whatever you are standing in.
tar -czf "$TARBALL" -C "$STAGE" .
rm -rf "$(dirname "$STAGE")"
echo "Built: $TARBALL"
echo "Install on another Linux/GNOME box:"
echo "   cd ~ && tar xzf $(basename "$TARBALL") && ./install.sh"
