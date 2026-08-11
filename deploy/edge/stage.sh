#!/usr/bin/env bash
# Stage the built dashboard for the single-endpoint front door.
#
# The static dist is a *development* Angular build, so API_BASE_URL is compiled
# into main.js as a literal — unlike the production Docker image, where
# replacements.sed substitutes it at container start. Serving that bundle behind
# a proxy without rewriting it gives you one URL for the page and a second one
# for every XHR, which is the two-origin problem wearing a disguise.
#
# So: copy the dist, rewrite the baked origin, serve the copy. The source dist
# is never modified — rerunning gauzy-stack rebuilds it and would undo an
# in-place edit anyway.
#
#   ./stage.sh [/path/to/dist/apps/gauzy]

set -euo pipefail

SRC="${1:-$HOME/ever-gauzy/dist/apps/gauzy}"
DEST="$(cd "$(dirname "$0")" && pwd)/www"
FROM="${FROM_ORIGIN:-http://localhost:3000}"
TO="${PUBLIC_URL:-http://localhost:8080}"

[ -f "$SRC/index.html" ] || { echo "no build at $SRC — run 'gauzy-stack build' first" >&2; exit 1; }

echo "staging  $SRC"
echo "      -> $DEST"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -r "$SRC/." "$DEST/"

# Every occurrence, uniformly. The four in main.js are API_BASE_URL itself, a
# guard that compares an endpoint against that same default, and two OAuth
# redirect URLs — all of which should now point at the single origin. Rewriting
# them as a set is what keeps the guard's meaning intact.
# `|| true` on every grep here: with `set -o pipefail`, grep's exit 1 for "no
# matches" fails the pipeline — and no matches is exactly what success looks
# like on the verification pass below.
hits=$(grep -rlF "$FROM" "$DEST" --include='*.js' 2>/dev/null | wc -l || true)
grep -rlF "$FROM" "$DEST" --include='*.js' 2>/dev/null | xargs -r sed -i "s|$FROM|$TO|g" || true
echo "rewrote  $FROM -> $TO in $hits file(s)"

remaining=$(grep -roF "$FROM" "$DEST" --include='*.js' 2>/dev/null | wc -l || true)
[ "$remaining" -eq 0 ] || { echo "WARNING: $remaining occurrence(s) of $FROM remain" >&2; exit 1; }
echo "done — $(grep -roF "$TO" "$DEST" --include='*.js' 2>/dev/null | wc -l || true) reference(s) now point at $TO"
