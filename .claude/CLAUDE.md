# System-Tracker

Per-employee activity tracking for Ubuntu developer workstations. Two halves:
a custom tracker filling the gaps neither Gauzy's desktop agent nor
ActivityWatch covers on Linux — chiefly **headless/background processes**,
which neither tool sees — and **Ever Gauzy** (AGPL-3.0) as the org/reporting
layer, now **vendored under `gauzy/`** and modified in place.

`/home/sys0041/ever-gauzy` is the historical checkout the vendored tree was
copied from. It is no longer the source of truth; edit `gauzy/` instead.

## Layout

```
tracker/proc_tracker.py                the tracker — the whole product, ~670 lines
tracker/report.py                      CLI running-time report (imports proc_tracker)
tracker/config.example.json            copy to tracker/config.json (gitignored)
tracker/README.md                      usage, config table, session-backend matrix
gauzy/                                 vendored Ever Gauzy (12k files), ours to edit
deploy/docker-compose.yml              dashboard + API behind ONE endpoint
deploy/.env.example                    copy to deploy/.env (gitignored)
dashboard-mods/README.md               what we changed in gauzy/, and the build runbook
config/minimal-tracking-features.sql   Gauzy sidebar trim via feature toggles
docs/railway-deployment.md             Railway runbook for the single-endpoint setup
docs/single-endpoint-deployment.md     why one URL, and the shape of it
docs/feasibility.md                    original assessment (Xorg question resolved at top)
docs/HANDOVER.md                       current state, screenshot findings, open items
README.md                              scope + platform capability matrix
```

The tracker is stdlib-only Python and stays that way; `gauzy/` is a Node/Angular
monorepo with entirely different rules. The stdlib-only constraint below applies
to `tracker/`, not to `gauzy/`.

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

- **One endpoint.** `deploy/docker-compose.yml` publishes only the webapp;
  nginx serves the dashboard at `/` and proxies `/api/` to the API internally,
  so there is a single origin and no CORS. Neither the API nor the database is
  reachable from outside. Default `http://localhost:8080`.
- The older two-port arrangement (`:4200` dashboard, `:3000` API, `:5432` DB,
  all published — `gauzy/docker-compose.demo.yml`) is what this replaces. The
  legacy containers are named `db` / `api` / `webapp`; the new ones are
  `st-db` / `st-api` / `st-webapp`.
- `docker exec -i st-db psql -U postgres -d gauzy` for the database.
- After applying `config/minimal-tracking-features.sql`, users must **fully log
  out and back in** — a refresh is not enough, the old feature list is cached in
  `localStorage` (`_gauzyStore`).
- IDs (org, tenant, employee) and credentials for the local instance are in
  `docs/HANDOVER.md` §7. `tracker/config.json` is gitignored — never commit it.

## Licence

**Gauzy is now vendored under `gauzy/`.** This supersedes the earlier rule
against vendoring — it was a deliberate decision, not an oversight.

What vendoring does and does not grant:

- It grants the right to **copy and modify**. AGPL-3.0 says so explicitly.
- It does **not** transfer ownership or allow relicensing. `gauzy/` stays
  AGPL-3.0, copyright Ever Co. LTD. `gauzy/LICENSE` and the copyright headers
  are not ours to remove, however much of the code we rewrite.
- Rebranding off the **"Ever"/"Gauzy" marks is permitted and expected** —
  trademarks are not covered by the AGPL grant, so if this is presented as our
  product the marks must go. That is separate from the licence, which stays.
- Deploying a *modified* Gauzy to users over a network triggers **AGPL §13**:
  the modified source must be offered to those users. Internal-only use is the
  simpler position.

`tracker/` is a **separate program** — it talks to Gauzy over HTTP and shares no
process, no linkage and no build. Living in the same repo is aggregation, not
combination, and does not pull the tracker under the AGPL. Keep it that way:
do not import Gauzy code into `tracker/`, and do not make the tracker part of
the Gauzy build.
