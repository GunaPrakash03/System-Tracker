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

## What it captures

Per matched process, per interval: process **name**, **CPU %** for the interval
(in `metaData`), and a duration. Kernel threads are excluded. Verified capturing
`postgres`, `dockerd`, `containerd`, `node`, `nginx`, `code`, `java`, `python3`,
`chrome` in a live test.

## What it does NOT capture

- **Keyboard/mouse activity** — that's the Gauzy agent's job; this reports
  process presence + CPU, and posts `keyboard:0, mouse:0`.
- **Browser tabs / URLs** — a process scan sees `chrome`, not the site. For
  YouTube/Spotify and per-URL data use ActivityWatch's browser watcher.
- **"Actively working" vs "just running"** — a daemon runs whether or not
  anyone touches it. CPU % is a proxy for activity, not proof of engagement.

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
