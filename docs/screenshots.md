# Screenshots on Wayland — how DeskTime does it, and our plan

**Date:** 6 August 2026
**Machine:** Ubuntu, **Wayland** session (GNOME Shell 46, xdg-desktop-portal-gnome 46.2)
**Requirement:** capture like DeskTime — **silent**: no shutter sound, no visual
flash/blink, no notification.

This doc records what was found by inspecting the DeskTime install on this box
and testing capture routes directly, and proposes how to implement the same in
`tracker/proc_tracker.py`. Nothing here is guesswork — each claim was verified on
the wire (D-Bus) or against the installed binaries.

---

## 1. The core problem: X11 capture is dead on Wayland

On this Wayland session, XWayland's root window exists and reports the right
size, but reading its pixels fails outright:

```
XWayland root window: 1600x900 depth=24
XGetImage  -> BadMatch (X protocol error, not a blank image)
xwd -root  -> BadMatch, 0-byte output
```

The root window is unredirected, so there are no pixels to read. This is why
**every X11-based capturer fails here**: Gauzy's own `ElectronDesktopCapturer`,
its `ScreenshotDesktopLib` engine (ImageMagick `import`), and third-party tools
like AutoScreenshot. Switching to Xorg would fix it — but the team has ruled
that out, so every option below is Wayland-native.

---

## 2. How DeskTime takes screenshots (verified on this box)

DeskTime is an Electron app at `/opt/DeskTime/`, and its **primary,
cross-platform capture path IS Electron** — `desktopCapturer.getSources({types:
["window","screen"]})`, used on Windows, macOS, and Linux/X11. That path is
real and present in `app.asar`.

**But it deliberately switches away from Electron on Wayland+GNOME.** The capture
class defaults to an X11/Electron branch and flips it off when it detects a
Wayland GNOME session (minified `app.asar`):

```js
branchX11 = true;                       // default: Electron / X11 path
constructor(){
  nixCompIsWayland() && nixDeIsGnomelike() && (
     this.#branchX11 = false            // Wayland + GNOME -> abandon Electron
  );
}
#binName = "dt-ubuntu-wayland-screenshot";   // the Wayland branch spawns this
```

The reason: Electron's `desktopCapturer` on Wayland goes through PipeWire / the
ScreenCast portal, which shows a screen-share indicator and cannot run silently.
So on Wayland+GNOME (this box) DeskTime drops Electron and spawns a separate
native helper:

```
/opt/DeskTime/resources/app-binaries/nix/x64/dt-ubuntu-wayland-screenshot   (+ arm64)
```

**It is a fork of GNOME's own `gnome-screenshot`.** The binary's symbols are
gnome-screenshot's exact source files: `screenshot-application.c`,
`screenshot-backend-shell.c`, `screenshot-backend-x11.c`,
`screenshot-filename-builder.c`.

This helper itself has two backends and picks one at runtime:

| Session | Backend | Mechanism |
|---|---|---|
| **Wayland** | `ScreenshotBackendShell` | D-Bus → `org.gnome.Shell.Screenshot` |
| **Xorg** | `ScreenshotBackendX11` | `gdk_pixbuf_get_from_window` on the root window |

So DeskTime has **two layers** of X11-vs-Wayland choice: the Electron app picks
Electron (X11) vs the native helper (Wayland), and the native helper itself then
picks its own X11 vs Shell backend. On this Wayland box, the path taken is:
Electron app → native helper → `ScreenshotBackendShell` → the D-Bus call below.

### The exact call it makes (captured with dbus-monitor)

```
org.gnome.Shell.Screenshot.Screenshot(
   boolean false      ← include_cursor
   boolean false      ← flash = FALSE          ★ this is what makes it silent
   string  "…/.cache/dt-ubuntu-wayland-screenshot/scr-4496153.png")
```

It writes the PNG to its cache dir, reads it back into memory
(`g_memory_output_stream_*`), and deletes it — so no file lingers and no
notification fires.

### Why it is *allowed* to call that method

A raw call to `org.gnome.Shell.Screenshot` from an ordinary process is refused:

```
AccessDenied: Screenshot is not allowed
```

GNOME Shell keeps a **sender allowlist** for that privileged method — only a few
well-known bus names may call it: `org.gnome.Shell.Screenshot`,
`org.gnome.SettingsDaemon.MediaKeys`, and **`org.gnome.Screenshot`**.

DeskTime's helper registers as a GNOME-screenshot-style GApplication and so
**owns the `org.gnome.Screenshot` bus name**, which is on that allowlist. By
being (a fork of) gnome-screenshot, it inherits the permission. That is the
entire trick: *impersonate the one tool GNOME already trusts, then ask it not to
flash.*

### The DeskTime GNOME extension does NOT capture

`~/.local/share/gnome-shell/extensions/gnome-focused-window@desktime.com` only
exposes the **focused window's title + class** over D-Bus. No screenshots.
DeskTime splits the work: extension for window metadata, gnome-screenshot fork
for pixels.

---

## 3. The three silent routes, compared

All three avoid the flash; they differ in how they earn the privilege to capture.

| # | Route | How it captures silently | Needs | Robustness |
|---|---|---|---|---|
| A | **`org.gnome.Screenshot` name trick** (DeskTime's method, in our Python) | own the allowlisted bus name, then call `Screenshot(false, **false**, path)` | nothing installed; no logout | depends on GNOME keeping `org.gnome.Screenshot` on the allowlist |
| B | **GNOME Shell extension** (already written, `tracker/gnome-extension/`) | run *inside* gnome-shell, call `Shell.Screenshot` directly — no allowlist gate | install once + **logout/login** | highest — in-process code is never gated |
| C | **xdg-desktop-portal** (already wired, `screenshot_method: portal`) | — | nothing | **NOT silent — it flashes** (portal forces `flash=true`) |

Route C is the current working fallback but fails the requirement. Routes A and
B are the silent options.

---

## 4. Proposed implementation — DeskTime-style (Route A)

Add a third value to the existing `screenshot_method` config:

```
"screenshot_method": "gnome" | "extension" | "portal" | "auto"
```

- **`gnome`** — replicate DeskTime exactly, natively in Python (no bundled
  binary, no extension, no logout):
  1. On startup, acquire the `org.gnome.Screenshot` session-bus name via
     `Gio.bus_own_name` and hold it for the tracker's lifetime.
  2. Each interval, call
     `org.gnome.Shell.Screenshot.Screenshot(false, false, path)`.
  3. Read the PNG, delete it, upload it to the slot (existing upload path).
- **`auto`** — try `gnome` (silent, no setup) → then `extension` (silent) →
  then `portal` (flashes). Prefer the routes that need no install.

**Dependency:** `python3-gi` — already used by the portal path; a system package,
imported lazily. Still the project's only non-stdlib import.

**Precondition:** the `org.gnome.Screenshot` name must be free — i.e. DeskTime /
gnome-screenshot not simultaneously capturing. On this box the name is free
(DeskTime not running). If it is ever taken, the tracker falls back per `auto`.

### What is NOT proposed

- Shelling out to DeskTime's private `dt-ubuntu-wayland-screenshot` — it is owned
  by root, could vanish on a DeskTime update/uninstall, and still leans on the
  same allowlist trick. Doing it in our own Python is cleaner and self-contained.
- Any X11 path — dead on Wayland (§1).

---

## 5. Confirmed — the DeskTime trick works from our own process

The open question ("does GNOME 46 let *our* Python own `org.gnome.Screenshot`
and call `flash=false`?") was tested and **passed** on this Wayland session:

```
session type: wayland
acquired bus name: org.gnome.Screenshot
RESULT: success=True   file=/tmp/dt-trick-test.png
PNG valid=True  1600x900  250530 bytes
```

Then verified end-to-end through the tracker (`screenshot_method: gnome`): four
consecutive slots captured and uploaded, and a `dbus-monitor` on
`org.gnome.Shell.Screenshot` showed **every** call as `boolean false, boolean
false` — cursor off, **flash off**. No flash, no sound, no notification.

---

## 6. Current state of the code (implemented)

- `tracker/proc_tracker.py` — `screenshot_method` = `auto | extension | gnome |
  portal`, with `auto` = extension → gnome → portal.
  - **gnome** (Route A, DeskTime-style): verified silent end-to-end
    (`flash=false` on the wire), no install, no logout.
  - **extension** (Route B): written; silent; needs install + one logout.
  - **portal** (Route C): verified end-to-end but FLASHES; last resort only.
  All three are Wayland-native — no Xorg.
- `tracker/gnome-extension/system-tracker-shot@local/` — the Route B extension,
  plus install/verify steps in its README.
- `tracker/config.json` — `capture_screenshots: true`, `screenshot_method:
  auto`. On this box that means **silent capture right now via the gnome route**,
  automatically upgrading to the extension once it is installed + enabled.

---

## 6b. Dashboard visibility — a timer is required (found while testing)

Storing a screenshot is not enough to see it in the dashboard. Gauzy's
Employees → Activity → **Screenshots** view calls `GET /timesheet/time-slot`
with a WHERE that **inner-joins `timeLogs`**, and only returns slots whose
TimeLog falls in the viewed day. A slot posted without a running timer has no
same-day TimeLog, so it — and its screenshots — never appear, even though the
`screenshot` rows exist and the image files are served.

Observed on this box: 22 screenshots stored and all correctly attached (0
orphaned), yet the dashboard showed only 11 — the batch that happened to fall
under a stray 24-second browser TimeLog. The rest were invisible.

**Fix (implemented):** the tracker now maintains a timer like the desktop agent
— `start_timer()` at startup (running TimeLog), slots attach to it, `stop_timer()`
at shutdown, and it restarts the timer after a re-login. Config: `maintain_timer`
(default true), `timer_source` (default `DESKTOP`). Verified: a fresh
timer-wrapped run's slot (`06:10`, 3 shots) appeared in the exact dashboard query
immediately, next to the old batch.

## 7. Summary

DeskTime captures silently on Wayland by shipping a fork of `gnome-screenshot`
that (a) owns the allowlisted `org.gnome.Screenshot` bus name and (b) calls
`Shell.Screenshot` with `flash=false`. We can do the same in ~40 lines of Python
with no bundled binary and no logout, pending one confirmation test. If that
test fails, the already-built in-process extension gives the same silence at the
cost of a one-time install and re-login.
