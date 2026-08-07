# System-Tracker

Per-employee activity tracking for Ubuntu developer workstations. **Ever Gauzy**
(`/home/sys0041/ever-gauzy`, AGPL-3.0, read-only reference) is the org/reporting
layer; this repo holds a custom tracker that fills the gaps neither Gauzy's
desktop agent nor ActivityWatch covers on Linux — chiefly **headless/background
processes**, which neither tool sees.

## Layout

```
tracker/proc_tracker.py                the tracker — the whole product, ~670 lines
tracker/report.py                      CLI running-time report (imports proc_tracker)
tracker/config.example.json            copy to tracker/config.json (gitignored)
tracker/README.md                      usage, config table, session-backend matrix
config/minimal-tracking-features.sql   Gauzy sidebar trim via feature toggles
docs/feasibility.md                    original assessment (Xorg question resolved at top)
docs/HANDOVER.md                       current state, screenshot findings, open items
README.md                              scope + platform capability matrix
```

## Commands

```bash
cp tracker/config.example.json tracker/config.json   # then edit credentials
python3 tracker/proc_tracker.py                      # uses ./config.json next to the script
python3 tracker/proc_tracker.py /path/to/config.json
python3 tracker/report.py --no-gauzy                 # offline running-time table
```

Credentials may come from `GAUZY_URL` / `GAUZY_EMAIL` / `GAUZY_PASSWORD` instead
of the config file (env wins — see `load_config`). A systemd user-unit template
is in `tracker/README.md`; it is not installed.

There is no build, no test suite, no dependency manifest, and no linter config.
Verification is running the tracker for an interval and reading its log line.

## Hard constraints — do not break these

- **Stdlib only.** Python 3.8+, zero `pip install`. External data comes from
  `/proc`, `xprop`, `busctl`, and `libX11`/`libXss` via `ctypes`. `xdotool`,
  `wmctrl`, and `xprintidle` are deliberately *not* used and are not installed
  on the target box. Do not introduce `psutil`, `requests`, `Xlib`, etc.
- **Both session backends stay working.** Every OS-level signal has an X11 path
  and a Wayland fallback, selected at runtime by `ON_X11`
  (`DISPLAY` + `XDG_SESSION_TYPE`). Adding an X11-only feature is fine; making
  the tracker *require* X11 is not.

| Signal | X11 (current session) | Wayland fallback |
|---|---|---|
| Focused window | `xprop _NET_ACTIVE_WINDOW` | "Focused Window D-Bus" GNOME extension |
| All open windows | `xprop _NET_CLIENT_LIST` — all windows + titles | impossible, returns `[]` |
| Focus → process | exact, via `_NET_WM_PID` | token guess from `wm_class` |
| Input idle | XScreenSaver via `ctypes` | GNOME Mutter `IdleMonitor` |

- **Gauzy compatibility.** The tracker posts to `POST /api/timesheet/time-slot`
  — the same endpoint and payload shape as the official desktop agent — so data
  lands under **Time & Activities → Apps**. Changing that shape breaks the
  dashboard. `overall` (active seconds) is what drives Gauzy's activity %.
- **Employee account required.** Login must resolve to an employee/org/tenant
  triple or `GauzyClient.login()` raises. Super-admin alone is not enough.

## Known ceilings — settled, don't re-litigate

- **Browser URLs and background tabs are unavailable.** Tabs are not OS windows.
  X11 reveals every browser *window* and its active tab's **title**; no window
  property carries a URL. Full per-URL history needs a browser extension (out of
  scope by request) or AT-SPI. Titles only.
- **Keyboard/mouse intensity** is posted as a 0/1 flag, not counts — that is the
  Gauzy agent's job. `foregroundSeconds` is this tracker's engagement signal.
- **Screenshots are not this tracker's job** and never will be; they belong to
  the Gauzy desktop agent. Every server-side screenshot toggle is already on —
  Wayland, not permissions, was the historical blocker. Details in
  `docs/HANDOVER.md` §4.

## Code conventions

`proc_tracker.py` is a single flat module with banner-comment sections
(`# --- Config`, `# --- /proc scanner`, …) and no classes except `GauzyClient`.
Follow that: plain functions, explicit `try/except` around every OS call
returning `None`/`[]` on failure rather than raising, and docstrings that explain
*why a platform behaves that way*, not just what the function does. That
platform reasoning is the most valuable content in the file — preserve it when
editing. `report.py` imports `proc_tracker` as a library (`import proc_tracker as pt`),
so keep its helpers (`scan_proc`, `compile_patterns`, `match`, `fmt_duration`,
`load_config`, `GauzyClient`) importable and side-effect-free at module level.

Docs are prose-heavy and use tables for capability matrices; keep new docs in
that register. British spelling in the existing prose.

## Environment facts

- Gauzy API `http://localhost:3000`; the Gauzy DB runs in a container named `db`
  (`docker exec -i db psql -U postgres -d gauzy`).
- After applying `config/minimal-tracking-features.sql`, users must **fully log
  out and back in** — a refresh is not enough, the old feature list is cached in
  `localStorage` (`_gauzyStore`).
- IDs (org, tenant, employee) and credentials for the local instance are in
  `docs/HANDOVER.md` §7. `tracker/config.json` is gitignored — never commit it.

## Licence

Gauzy is AGPL-3.0. Configuration (feature toggles) creates no obligation.
Deploying a *modified* Gauzy to users outside the company triggers AGPL §13 and
requires rebranding off the "Ever"/"Gauzy" marks. Code in this repo is separate
and carries its own licence — keep it that way; do not vendor Gauzy source here.
