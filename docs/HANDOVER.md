# System-Tracker — Handover Summary

**Date:** 5 August 2026
**Repo:** `/home/sys0041/System-Tracker` (branch `main`)
**Machine:** Ubuntu, session now **Xorg** (was Wayland — this matters, see §3)
**Related tree:** `/home/sys0041/ever-gauzy` (Ever Gauzy source, AGPL-3.0, read-only reference)

---

## 1. What this project is

Per-employee activity tracking for developer workstations, built on **Ever Gauzy**
as the organisation/reporting layer, with a custom tracker filling the gaps that
neither Gauzy's desktop agent nor ActivityWatch covers on Linux.

Two original requests drove it:

1. **Trim the Gauzy UI** down to tracking + employees only — done, no code changes.
2. **Track background/headless apps** (node, docker, postgres, VS Code, Postman)
   not just the focused window — done, custom `/proc` tracker.

---

## 2. Current state

| Component | File | State |
|---|---|---|
| Process/window/activity tracker | `tracker/proc_tracker.py` | Working, pushes to Gauzy |
| Per-app running-time report (CLI) | `tracker/report.py` | Working |
| Gauzy sidebar trim | `config/minimal-tracking-features.sql` | Written, applied via psql |
| Feasibility assessment | `docs/feasibility.md` | Historical; Xorg question now resolved |

Nine commits, latest `fd87514`. Working tree clean at time of writing.

### The tracker in one paragraph

`proc_tracker.py` is stdlib-only Python. Every `interval_seconds` (default 60) it
scans `/proc` for every running process, samples the focused window every
`focus_sample_seconds` (default 5) to split foreground vs background time, decides
active-vs-idle, enumerates all open windows, and POSTs one time-slot to
`/api/timesheet/time-slot` — the same endpoint the official desktop agent uses, so
the data lands under **Time & Activities → Apps**.

Copy `tracker/config.example.json` → `config.json` (gitignored) and run:

```bash
python3 tracker/proc_tracker.py              # uses ./config.json
python3 tracker/report.py --no-gauzy         # offline running-time table
```

Credentials can come from `GAUZY_URL` / `GAUZY_EMAIL` / `GAUZY_PASSWORD` instead
of the file. A systemd user-unit template is in `tracker/README.md`.

---

## 3. The Xorg switch — the main change in this session

The machine was moved from a Wayland login to **Xorg**. This is the single most
consequential environment fact in the project, because Wayland forbids one app
from seeing another app's windows. Everything below became possible only because
of that switch, and is implemented in commit `fd87514`.

| Signal | X11 (now) | Wayland (before / fallback) |
|---|---|---|
| Focused window | `xprop` `_NET_ACTIVE_WINDOW` — **no GNOME extension** | "Focused Window D-Bus" GNOME extension, **required** |
| All open windows | `_NET_CLIENT_LIST` — **every window + title** | ✗ impossible |
| Focus → process | exact, via the window's `_NET_WM_PID` | name-token guess from `wm_class` |
| Input idle | XScreenSaver (`libXss`, via `ctypes`) | GNOME Mutter IdleMonitor |
| Screen capture | works (verified) | blank/fails |

**Backends are chosen automatically** from `DISPLAY` / `XDG_SESSION_TYPE`, and the
Wayland route stays as fallback — so reverting the session to Wayland degrades
capability but does not break the tracker. Verified by forcing `ON_X11 = False`.

Concrete gain, observed live: a background Chrome window's tab title is now
captured alongside the focused one, which was invisible before.

```
chrome  fg=0s wins=2 | Running for 9m 5s — "… - Slack - Google Chrome"; "Gauzy - Google Chrome"
```

Reported as `windowTitles` / `windowCount` in each APP activity's `metaData`.

---

## 4. Screenshots — investigated, no dashboard change needed

The question was where a super admin enables screenshots. **Answer: nowhere — every
server-side toggle was already on.** Verified against the running API:

```
Default Company:  allowScreenshotCapture = True    screenshotFrequency = 10   enforced = False
Employee:         allowScreenshotCapture = True
```

Both default to `true` in the entities (`organization.entity.ts:403`,
`employee.entity.ts:382`).

The `false` values in the agent's local config (`~/.config/Gauzy Agent/config.json`:
`auth.allowScreenshotCapture`, `appSetting.allowScreenshotCapture`) are a **red
herring** — the gate is an OR, not an AND (`desktop-screenshot.ts:527`):

```ts
return Boolean((auth?.allowScreenshotCapture ?? false) || (auth?.user?.employee?.allowScreenshotCapture ?? false));
```

The employee flag alone satisfies it. Permission was never the blocker — **Wayland
was**. The agent uses `SCREENSHOTS_ENGINE_METHOD = "ElectronDesktopCapturer"`,
which captures via X11 and returns blank under Wayland. X11 capture was tested
directly on this session and works (`XGetImage` → non-empty 1600x900 framebuffer).

### Where the toggles live, for reference

- **Org:** Settings → Organizations → *Default Company* → Edit → **Settings** tab →
  **Timer Settings** — "Allow Screen Capture"
  (`edit-organization-other-settings.component.html:687`)
- **Employee:** Employees → *employee* → Edit → **Settings** tab → same label
  (`edit-employee-other-settings.component.html:145`)
- **View captures:** Employees → Activity → Screenshots

### Setting the screenshot interval — the catch

The **Screenshot Frequency** dropdown is hidden inside `@if (isEnforced)`, and the
org currently has `enforced = False`. So the field is invisible until the
**"Enforced"** toggle (same Timer Settings section) is switched on.

- Allowed values: **1, 3, 5, 10** (`constants/src/lib/organization.ts:57`)
- Unit is **minutes** — `desktop-timer.ts:269` schedules `60 * 1000 * updatePeriod`
- Current value: 10

**Enforced is not merely a reveal switch.** Per its tooltip (`en.json:2878`) it makes
track-on-sleep, random screenshot and screenshot frequency *mandatory and not
overridable by users* — a policy change, not just a UI one. The alternative, if
org-wide enforcement isn't wanted, is the **Gauzy Agent app → Settings → Screenshot
frequency** (same 1/3/5/10 options), which is per-machine. There is no per-employee
frequency field in the web dashboard.

After changing it, restart the agent — the org value is read into
`timer.updatePeriod` at login (`time-tracker.component.ts:2188`), so a running agent
keeps the old interval.

---

## 5. Hard limits — do not re-litigate these

- **Browser tabs / URLs.** Xorg reveals every browser *window* and its active tab's
  title, but tabs are not OS windows: other tabs in a window stay invisible, and no
  window property carries a URL. Only window **titles** are ever available. Full
  per-URL history needs a browser extension (explicitly out of scope by request) or
  AT-SPI accessibility integration (see §6).
- **Keyboard/mouse intensity.** The custom tracker posts `keyboard`/`mouse` as a
  0/1 flag, not counts — that's the Gauzy agent's job. "Foreground seconds" is the
  engagement signal instead.
- **Screenshots are not the custom tracker's job.** `proc_tracker.py` does not and
  will not capture them; that is entirely the Gauzy desktop agent.

---

## 6. Open items / next steps

1. **Start the Gauzy Agent and confirm screenshots actually land.** It is installed
   (`~/.config/Gauzy Agent/`, last written 18:22 on 5 Aug) but was **not running**.
   Let it run past one 10-minute interval, then check Employees → Activity →
   Screenshots. If images still don't appear, trace the agent's upload path — the
   capture side is proven working.
2. **Decide on screenshot interval policy** — leave at 10 min, or enable *Enforced*
   to expose the dropdown, accepting that it locks the setting for all members (§4).
3. **Media categorisation (YouTube/Spotify, watching vs background audio)** — still
   unbuilt. Scope item 3 in the root README. The tracker already detects audio
   playback via `/proc/asound` for active/idle; classification by site is not done.
4. **AT-SPI for real browser URLs** — optional, unbuilt. Python bindings are already
   installed here; needs `toolkit-accessibility` enabled (currently `false`) and
   Chrome started with `--force-renderer-accessibility`, which adds browser runtime
   overhead. Only worth it if per-URL data is genuinely required.
5. **Run the tracker as a service** — systemd unit template exists in
   `tracker/README.md` but is not installed.

---

## 7. Environment facts worth keeping

**Security decisions taken 2026-08-07**

- **Sentry disabled.** `SENTRY_DSN` in `~/gauzy/.env.demo.compose` pointed at Ever
  Co's Sentry project (`o51327.ingest.sentry.io`). Unhandled API exceptions —
  which can carry request payloads, employee ids and stack traces — were being
  sent to a third party outside the organisation, and this host can reach
  `sentry.io`. The value is now empty and the API was recreated to pick it up.
  A backup of the original file is `.env.demo.compose.bak`.
  `POSTHOG_KEY`, `JITSU_*` and the AWS keys were already empty, and the browser
  bundle ships Sentry code with no populated DSN, so nothing reported from
  employees' browsers.
- **Credential files are 0600.** `tracker/config.json`, the installed copy under
  `~/.local/share/system-tracker/`, and `.env.demo.compose` all held secrets at
  0664 — readable by any local user. `packaging/install.sh` now creates the
  config 0600 before writing to it.
- **Still outstanding:** the tracker authenticates as `admin@ever.co` / `admin`.
  Each workstation should use its own employee account, and the default password
  must change before the box is reachable by anyone else.


- Gauzy API: `http://localhost:3000`; login `admin@ever.co` / `admin` (Super Admin,
  and also an Employee — the tracker requires an employee record to attach
  activities to).
- Org `Default Company` = `9d8d8eff-e6de-48b7-92d9-dc8dd011e3b6`
  Tenant = `547e1931-eff4-42a2-a170-47db5e411894`
  Employee = `f58e24df-e425-48c1-a2d3-298c10a78acc`
- Present on the box: `xprop`, `xinput`, `libXss`. **Not** installed: `xdotool`,
  `wmctrl`, `xprintidle` — the tracker deliberately needs none of them.
- After running the sidebar-trim SQL, users must **fully log out and back in** — a
  refresh is not enough, the old feature list is cached in `localStorage`
  (`_gauzyStore`).

---

## 8. File map

```
README.md                              project scope + platform capability matrix
docs/feasibility.md                    original assessment (+ Xorg resolution note at top)
docs/HANDOVER.md                       this file
config/minimal-tracking-features.sql   sidebar trim via Gauzy feature toggles
tracker/proc_tracker.py                the tracker (stdlib only)
tracker/report.py                      CLI running-time report
tracker/README.md                      usage, config table, session-backend matrix
tracker/config.example.json            copy to config.json (gitignored)
```

Key functions in `proc_tracker.py`: `list_windows()` (all open windows, X11),
`get_focused()` / `get_focused_x11()` (focus + owning PID),
`get_idle_seconds()` / `get_idle_seconds_x11()` (idle), `scan_proc()` (process scan),
`build_process_rows()` (per-interval aggregation), `GauzyClient.post_time_slot()`
(API push).
