# Admin settings app

The surface where a super admin sets the things Gauzy has no field for. The
tracker reads it live; nothing here requires a restart on either side.

| Setting | Why it is not in Gauzy |
|---|---|
| Screenshot interval, per employee | Gauzy's `screenshotFrequency` is organisation-wide. There is no per-employee equivalent. |
| Media counts as idle, per employee | No such concept exists in Gauzy at all. |
| App productivity category, per department | Gauzy has departments, but no notion of an app being productive *within* one. |

## Why a separate app rather than extending Gauzy

Gauzy is AGPL-3.0 and this repo already carries three source patches against it,
each costing a ~25-minute `yarn install` + production rebuild whenever they
change. Putting admin fields there would put every future settings tweak behind
that same cycle. This app talks to Gauzy over its REST API instead, so it stays
outside that licence and restarts in a second.

Employees and departments are **read live from Gauzy** and never copied here.
Only the mappings Gauzy cannot express are stored locally, so there is never a
second list of "who works here" to keep in step.

## Run

```bash
cp config.example.json config.json     # then set the Gauzy credentials
python3 settings_app.py                # http://127.0.0.1:8600
```

Stdlib only — `http.server`, `sqlite3`, `urllib`. No pip install, matching the
tracker's constraint. State lives in `settings.db` (SQLite, gitignored).

Installed as a systemd user service alongside the tracker:

```bash
systemctl --user status system-tracker-admin
journalctl --user -u system-tracker-admin -f
```

## Point the tracker at it

In the tracker's `config.json`:

```json
"settings_source": "url",
"settings_url": "http://127.0.0.1:8600/api/settings"
```

Left at `"settings_source": "config"` the tracker never calls out and behaves
exactly as it did before this app existed.

## API

| Endpoint | Returns |
|---|---|
| `GET /api/settings?employeeId=…` | `{"screenshot_interval_seconds": 300, "count_audio_as_active": false}` |
| `GET /api/categories?employeeId=…` | `{"default": "Neutral", "apps": {"chrome": "Productive"}}` |

`/api/settings` returns **only keys an admin has actually set**. An unset value
is omitted rather than sent as `null` or as a guessed default — the tracker
treats any present key as an override, so emitting defaults here would silently
overrule every machine's own `config.json`.

## Behaviour worth knowing

**Screenshot intervals snap to the tracker's slot grid.** A shot can only be
uploaded once that interval's time-slot POST returns an id to attach it to, and
Gauzy's screenshot views are scoped to a same-day TimeLog — an unattached shot
is stored but never renders. So with a 60s scan interval, a 5-minute setting
fires on every 5th interval; a 30-second setting captures every 60s rather than
manufacturing invisible orphans.

**"Media counts as idle" only decides whether media *alone* is enough.** Real
keyboard or mouse input always counts as active, music or no music.

**Unchecked is not the same as off.** Leaving the media checkbox clear stores
*no opinion* (`NULL`), letting the machine's own config decide. It does not
force media to count as active — that would overrule a workstation that
deliberately set `count_audio_as_active: false` locally.

**Apps are matched on process name**, lowercased — what the tracker reports
(`chrome`, `code`, `postgres`). Not window titles, so all Chrome usage sits in
one category regardless of the site being viewed.

**Categories are applied at report time, never at capture time.** No captured
row ever carries a category. That is what lets re-classifying an app, or moving
someone between departments, correct historical reports too.

## Security

Binds to `127.0.0.1` and has **no login of its own**. Anyone who can reach the
port can turn a colleague's screenshots off. Before changing `bind_host`, put it
behind the same reverse proxy and authentication as Gauzy.
