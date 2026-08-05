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

## What it does NOT capture

- **Keyboard/mouse intensity** — that's the Gauzy agent's job; this posts
  `keyboard:0, mouse:0`. "Foreground seconds" is the engagement signal instead.
- **Full browser URLs or background tabs** — only window **titles**, never URLs.
  Xorg reveals every browser *window* and its active tab's title, but tabs are
  not OS windows: the other tabs in a window remain invisible, and no window
  property carries the URL. Full per-URL history needs a browser extension (out
  of scope here by request) or AT-SPI accessibility integration.
- **Screenshots** — not captured.

## Run as a service (systemd user unit)

```ini
# ~/.config/systemd/user/proc-tracker.service
[Unit]
Description=System-Tracker process tracker
After=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 %h/System-Tracker/tracker/proc_tracker.py %h/System-Tracker/tracker/config.json
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now proc-tracker
```

## How it maps to Gauzy

Each interval becomes one `POST /api/timesheet/time-slot` containing an
`activities[]` array — one `APP` activity per process (`title` = process name,
`type` = `APP`, `metaData` = `{source: "system-tracker", cpuPercent}`). This is
the same shape the desktop agent posts, so the data appears under
**Time & Activities → Apps** for the employee.
