# Silent screenshots on Wayland — GNOME Shell extension

The tracker's screenshot feature has two capture routes:

| Route | Silent? | Needs |
|---|---|---|
| **`org.gnome.Shell.Extensions.SystemTrackerShot`** (this extension) | **Yes** — no flash, no sound, no notification | install + enable once |
| `xdg-desktop-portal` (built-in fallback) | **No** — GNOME's portal flashes the screen on every shot | nothing |

On Wayland an ordinary process cannot capture the screen without either
flashing (portal) or being refused (`org.gnome.Shell.Screenshot` with
`flash=false` returns *"Screenshot is not allowed"* to unsandboxed callers).
Only code running **inside** GNOME Shell can capture silently — which is how
DeskTime and Hubstaff do it, and why they too ship a Shell extension. This
extension exposes a single D-Bus method that writes one PNG where the tracker
asks; the tracker then reads and deletes it.

## Install

```bash
DEST=~/.local/share/gnome-shell/extensions/system-tracker-shot@local
mkdir -p "$DEST"
cp system-tracker-shot@local/metadata.json system-tracker-shot@local/extension.js "$DEST"/
gnome-extensions enable system-tracker-shot@local
```

**Activation.** A brand-new extension is loaded by GNOME Shell when enabled.
If the D-Bus check below fails right after enabling, log fully out and back in
once — Wayland cannot restart the shell in place, so the first load may need a
fresh session. After that it starts automatically at every login.

## Verify it is live and silent

```bash
# 1. The interface is exported:
gdbus introspect --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/SystemTrackerShot | grep CaptureToFile

# 2. Take one — watch the screen: there must be NO flash.
gdbus call --session --dest org.gnome.Shell \
  --object-path /org/gnome/Shell/Extensions/SystemTrackerShot \
  --method org.gnome.Shell.Extensions.SystemTrackerShot.CaptureToFile /tmp/silent-test.png
#   -> (true,)   and /tmp/silent-test.png is a real screenshot, captured with no flash
```

With the extension enabled, set `"screenshot_method": "extension"` in
`config.json` to guarantee silence — in that mode the tracker takes the shot
silently or skips it, and never falls back to the flashing portal.

## What it does / does not do

- **Does:** on `enable()`, export `CaptureToFile(path) -> success` and, on each
  call, run `Shell.Screenshot.screenshot(include_cursor=false, …)` — no flash,
  no sound, no notification. On `disable()`, unexport and drop the object.
- **Does not:** capture on its own, store anything, phone home, or run any timer.
  It is a passive capture endpoint; the Python tracker decides when to call it.

## Uninstall

```bash
gnome-extensions disable system-tracker-shot@local
rm -rf ~/.local/share/gnome-shell/extensions/system-tracker-shot@local
```
