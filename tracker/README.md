# proc_tracker — background & backend process tracker

Records which processes are running per interval — GUI apps **and** headless
backends (node, postgres, docker, nginx…) plus dev tools (VS Code, Postman,
Antigravity) — and pushes them into Ever Gauzy as `APP` activities inside time
slots, via the same API the official desktop agent uses.

Fills the gap that both the Gauzy agent and ActivityWatch leave on Linux:
neither sees headless/background processes. Reads `/proc`, so it works on
**Wayland and X11** (no window-manager access needed).

## Requirements

- Python 3.8+ (stdlib only — no `pip install`)
- A reachable Gauzy server
- A Gauzy account that is an **Employee in an organization** (activities attach
  to an employee). `admin@ever.co` works on a default install.

## Usage

```bash
cp config.example.json config.json
# edit config.json — server_url, email, password
python3 proc_tracker.py            # uses ./config.json
python3 proc_tracker.py /path/to/config.json
```

Secrets can come from the environment instead of the file:

```bash
GAUZY_URL=http://localhost:3000 GAUZY_EMAIL=you@co GAUZY_PASSWORD=... \
  python3 proc_tracker.py
```

## Config

| Key | Meaning |
|---|---|
| `server_url` | Gauzy API base, e.g. `http://localhost:3000` |
| `email` / `password` | Login of an employee account |
| `interval_seconds` | Poll/report cadence (default 60) |
| `watchlist` | Case-insensitive regex patterns of process names to report. **Empty list** = report every user process above `cpu_min_percent` |
| `cpu_min_percent` | Threshold when `watchlist` is empty |
| `max_processes` | Cap reported processes per interval (busiest first) |
| `capture_screenshots` | Master enable — must be true for any capture. **Default `true`** |
| `screenshot_gate` | `dashboard` (the Employees-page toggle decides) \| `config`. Default `dashboard` |
| `screenshot_gate_refresh_seconds` | How often the dashboard toggle is re-read (default 30) |
| `screenshot_method` | `gnome` \| `extension` \| `auto` \| `portal`. See below. Default `gnome` — `auto` can flash |
| `screenshot_timeout_seconds` | Give up if capture does not answer (default 20) |
| `maintain_timer` | Keep a tracking timer running so slots appear in the dashboard. **Default `true`** — see *Dashboard visibility* |
| `timer_source` | Timer/TimeLog source label (default `DESKTOP`) |

## Continuous tracking — the timer (starts at login, cannot be stopped)

Gauzy's activity and **screenshot** views (Employees → Activity) only show time
slots joined to a **same-day TimeLog**. A slot posted on its own is stored
correctly but stays invisible there. So the tracker, like the official desktop
agent, **starts a timer** (creating a running TimeLog) and lets every posted
slot attach to it. Config: `maintain_timer` (default on), `timer_source`.

For **continuous, non-stoppable tracking** — begin at system start, no pause or
stop — two more settings, both on by default:

| Key | Default | Effect |
|---|---|---|
| `enforce_timer` | `true` | Every interval, if the timer was stopped/paused **from the dashboard**, it is restarted before posting. Any stop is undone within one interval. |
| `stop_timer_on_exit` | `false` | The timer is **left running** when the tracker exits, so a service restart keeps tracking unbroken. Only the machine shutting down ends it. |

Combined with running the tracker as a login service (below), tracking starts
when the session starts and runs continuously until shutdown. A user *can* click
stop in the dashboard, but the next interval re-asserts it — the button has no
lasting effect. (Truly removing the button is a Gauzy **source** change, which
this project deliberately avoids; enforcement gives the same result via config.)

Verified end-to-end: with the timer off, freshly posted slots and screenshots do
**not** appear in `GET /timesheet/time-slot` (the exact call the Screenshots
gallery makes); with it on, they appear immediately.

## Time — the system's local clock

By default the tracker records with the **system's local wall-clock time**
(`use_local_time: true`), so the dashboard shows the same time as the machine's
clock. A slot taken at 11:50 on the machine reads 11:50 in Gauzy — not a UTC
offset. Set `use_local_time: false` to record in UTC instead (then the org's
timezone setting governs how it is displayed).

## Active vs idle time

The tracker measures whether the machine is genuinely being used, from login
until shutdown (run it as a service — see below). Each moment counts as:

- **ACTIVE** — keyboard/mouse was used within `idle_threshold_seconds` (default
  180s / 3 min), **OR** audio/video is playing (background video/music keeps the
  time active even with no input, when `count_audio_as_active` is true).
- **IDLE** — none of the above for the whole threshold window.

Signals used (all dependency-free, work on Wayland and X11):
- **Input idle** — the X server's XScreenSaver counter on X11, else GNOME Mutter
  IdleMonitor (`GetIdletime`). Both were measured to agree to within ~6 ms.
- **Audio/video** — kernel `/proc/asound/.../status` (`RUNNING` = playing).

The active seconds per slot become Gauzy's **activity %** (active ÷ slot
duration), so the dashboard shows real engagement instead of a flat ~1%.

## What it captures

Each interval it reports, per app/process:

- **Process presence + CPU %** — every running app and headless backend from
  `/proc` (kernel threads excluded).
- **Foreground vs background** — by sampling the focused window every
  `focus_sample_seconds`, it records how many seconds each app was actually
  **on screen** (`foregroundSeconds` in `metaData`, `mode: foreground|background`).
  An app watched the whole minute shows ~100% activity; one merely running in the
  background shows ~0%.
- **All open windows + titles** (**X11 only**) — every window on the session,
  including ones never focused, as `windowTitles` / `windowCount` in `metaData`
  and appended to the activity description. See *Session backends* below.
- **Active browser tab** — while a browser (`browsers` list) is focused, the
  window title is recorded as a `URL` activity, so Gauzy's **Visited Sites**
  fills in. This is by **page title**, active tab only.

Verified live: `postgres`, `dockerd`, `containerd`, `node`, `nginx`, `code`,
`gnome-terminal-server`, `bash` captured; terminal correctly shown as foreground
(`fg=12s`) while backends show `fg=0s`; Chrome/Firefox titles resolve to tab names.
On Xorg, a background Chrome window's title is captured alongside the focused
one (`chrome … wins=['… - Slack - Google Chrome', 'Gauzy - Google Chrome']`).

## Session backends

Picked automatically at startup from `DISPLAY` / `XDG_SESSION_TYPE`; the Wayland
route is also the fallback if an X query returns nothing.

| Signal | X11 (Xorg) | Wayland |
|---|---|---|
| Focused window | `xprop` `_NET_ACTIVE_WINDOW` — **no extension needed** | "Focused Window D-Bus" GNOME extension (required) |
| All open windows | `xprop` `_NET_CLIENT_LIST` — **all windows + titles** | ✗ impossible — Wayland forbids it |
| Focused app → process | exact, via the window's `_NET_WM_PID` | name-token guess from `wm_class` |
| Input idle | XScreenSaver extension (`libXss`) | GNOME Mutter IdleMonitor |

Switching this machine's login session to **Ubuntu on Xorg** is what enables the
middle two rows — it was the open question in `docs/feasibility.md`.

## Screenshots (`capture_screenshots`)

Off by default — capturing someone's screen is a policy decision, not a default.
When on, one screenshot per interval is taken at the close of the slot window
and uploaded to `POST /api/timesheet/screenshot` with the `timeSlotId` returned
by the slot POST, so it appears against that slot in
**Employees → Activity → Screenshots**. The server builds the thumbnail itself.

### Turning screenshots on/off from the dashboard (`screenshot_gate`)

Screenshots are controlled from Gauzy, not the config file. With
`screenshot_gate: "dashboard"` (default), each interval the tracker reads the
employee's **"Allow Screen Capture"** flag and only captures when it is on:

- **Where the toggle is:** Employees → *employee* → **Edit** → **Settings** tab
  → **Timer Settings** → *Allow Screen Capture*. (Editable by an admin /
  super-admin; it writes the employee's `allowScreenshotCapture` field.)
- An admin flips it and the tracker obeys within
  `screenshot_gate_refresh_seconds` (default 30) — **no config edit, no
  restart**. The startup log and per-interval log show the state
  (`shots OFF (dashboard)` when disabled).
- `capture_screenshots` stays as a master switch: it must be true for capture to
  be possible at all, but the dashboard toggle is the day-to-day control.
- Set `screenshot_gate: "config"` to ignore the dashboard flag and let
  `capture_screenshots` alone decide (the old behaviour).

Verified: setting the employee's *Allow Screen Capture* off makes the tracker
report `False` and skip capture; turning it back on resumes capture.

### Silent operation (`screenshot_method`)

DeskTime-style capture: no shutter sound, no visual flash/blink, no
notification. All routes are Wayland-native (no Xorg); two are silent:

| `screenshot_method` | Route | Silent? | Setup |
|---|---|---|---|
| `extension` | in-process GNOME Shell extension | **yes** | install + one logout |
| `gnome` | own `org.gnome.Screenshot`, `Shell.Screenshot(flash=false)` — **exactly what DeskTime does on Wayland** | **yes** | none |
| `portal` | `xdg-desktop-portal` | **no** — FLASHES | none |
| `auto` | `extension` → `gnome` → `portal` | **not guaranteed** — flashes whenever both silent routes fail | none |

**`gnome` is the default, not `auto`.** This was learned the hard way: under
`auto`, the silent routes are tried per capture, and a route that succeeds at the
startup probe can still fail later — GNOME's sender allowlist for
`org.gnome.Screenshot` is the usual reason. Every such failure falls through to
the portal and **flashes the employee's screen**, intermittently, all day, with
the log still reporting "silent" from the startup probe.

A fixed method never falls back. Under `gnome` a failed capture is a *missing
screenshot* rather than a flash, which is the right trade for software that runs
unattended on someone else's desk. Use `extension` for the most durable silent
route (install from [`gnome-extension/`](gnome-extension/README.md), then it
auto-starts). Use `auto` only where a flash is acceptable and coverage matters
more than silence.

**Extension vs gnome — why keep both.** The `gnome` route works today with zero
setup, but leans on GNOME's sender allowlist for `org.gnome.Screenshot`, which a
future GNOME release may tighten. The extension runs *inside* gnome-shell and is
not subject to that allowlist, so it is the durable choice — at the cost of one
logout to load. `auto` gives you the no-setup route now and the durable route
once installed.

**Why the portal is not silent, and how the silent routes dodge it.** GNOME's
portal always calls `org.gnome.Shell.Screenshot` with `flash=true` — verified on
the bus, `boolean false(cursor) boolean true(FLASH)` — so it draws a white blink
every shot. That method's `flash=false` form is refused to ordinary callers
(`AccessDenied: Screenshot is not allowed`). Two ways past it:

- **`gnome`** owns the `org.gnome.Screenshot` bus name, which is on GNOME's
  sender allowlist for that method — the same identity DeskTime's bundled
  gnome-screenshot fork registers under — then calls it with `flash=false`.
  Confirmed on the wire: every call `boolean false, boolean false`.
- **`extension`** runs inside gnome-shell and calls `Shell.Screenshot` directly,
  which is not gated at all.

(No route emits a notification: zero `Notify` calls were seen on the bus.)

**Why not X11 at all.** On Wayland, XWayland's root window reports the right
geometry but `XGetImage` against it fails with **BadMatch** — a protocol error,
not a blank frame, because the root is unredirected:

```
XWayland root window: 1600x900 depth=24
XGetImage  -> BadMatch     xwd -root -> BadMatch, 0-byte output
```

That one fact explains every X11-based capturer failing here: Gauzy's
`ElectronDesktopCapturer`, its `ScreenshotDesktopLib` engine (ImageMagick
`import`), and third-party tools like AutoScreenshot.

### Requirements and behaviour

- **`python3-gi`** — a system package (preinstalled on Ubuntu GNOME), imported
  lazily. Without it the tracker still runs, minus screenshots, and says so at
  startup. It is the one non-stdlib import in the project.
- **No consent dialog** on either route: the extension is in-process, and the
  portal is called with `interactive: false` (answered directly on GNOME 46).
- Whichever route is used, the tracker reads the PNG and deletes the temp file,
  so nothing accumulates on disk.
- A failed capture or upload never interrupts process tracking — it just shows
  in the log line.

Verified end to end against a local Gauzy — the **portal** path (silent-extension
path is verified by the extension's own D-Bus test, since a Wayland shell cannot
be reloaded mid-session): consecutive slots, each screenshot stored,
thumbnailed, and `timeSlotId` set.

```
[10:16:44] ACTIVE 100% (15/15s) | 10 apps, on-screen: gnome-terminal-server | 0 tabs | shot 242KB
[10:17:00] ACTIVE 100% (15/15s) (audio 5s) | 10 apps, on-screen: chrome, … | 1 tabs | shot 257KB
```

## What it does NOT capture

- **Keyboard/mouse intensity** — that's the Gauzy agent's job; this posts
  `keyboard:0, mouse:0`. "Foreground seconds" is the engagement signal instead.
- **Full browser URLs or background tabs** — only window **titles**, never URLs.
  Xorg reveals every browser *window* and its active tab's title, but tabs are
  not OS windows: the other tabs in a window remain invisible, and no window
  property carries the URL. Full per-URL history needs a browser extension (out
  of scope here by request) or AT-SPI accessibility integration.
- **Keystrokes, clipboard, or file contents** — never touched.

## Start at login and run continuously (systemd user unit)

This is what makes tracking **begin when the session starts** and stay running.
The unit binds to the graphical session (needed for the Wayland screenshot and
focus signals), and `Restart=always` brings it straight back if it ever exits —
and because `stop_timer_on_exit` is false, that restart does not interrupt the
timer.

```ini
# ~/.config/systemd/user/proc-tracker.service
[Unit]
Description=System-Tracker process tracker
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 %h/System-Tracker/tracker/proc_tracker.py %h/System-Tracker/tracker/config.json
Restart=always
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now proc-tracker
systemctl --user status proc-tracker      # confirm it is active
journalctl --user -u proc-tracker -f      # watch its log
```

The tracker starts automatically at every login. To have it run even before an
interactive login (e.g. an auto-login kiosk), also enable lingering:
`sudo loginctl enable-linger $USER` — but the graphical session must exist for
capture to work, so login-triggered start is the normal mode.

## How it maps to Gauzy

Each interval becomes one `POST /api/timesheet/time-slot` containing an
`activities[]` array — one `APP` activity per process (`title` = process name,
`type` = `APP`, `metaData` = `{source: "system-tracker", cpuPercent}`). This is
the same shape the desktop agent posts, so the data appears under
**Time & Activities → Apps** for the employee.
