# Gauzy dashboard modifications — the proper (rebuilt) version

Three dashboard changes, applied to the **Gauzy Angular source** and deployed by
rebuilding the web app (not a runtime CSS/JS hack). Source edits live in
`gauzy-dashboard.patch`; this file is the build + deploy runbook.

## What the changes do

| # | Change | File |
|---|---|---|
| 1 | **Remove the start/stop timer** from the dashboard (users can't start/stop tracking) | `packages/ui-core/shared/src/lib/time-tracker/time-tracker/time-tracker.component.html` |
| 2 | **"Worked today" ticks every second** (live), re-syncing to the server each refresh | `packages/plugins/dashboard-time-track-angular-ui/.../time-tracking.component.ts` + `.html` |
| 3 | **Auto-refresh every 60s** instead of 5 min, so the dashboard pulls fresh DB data promptly | same `.ts` (`setAutoRefresh`) |
| 4 | **Settings → Tracker Settings** page: per-employee screenshot interval, media-as-idle, and per-department app categories | `apps/gauzy/src/app/pages/settings/tracker-settings/` (new) |
| 5 | Route + menu entry + translation for #4 | `settings.routes.ts`, `base-nav-menu.component.ts`, `i18n/en.json` |

Change #4 renders a page whose **data lives in `admin/settings_app.py`**, not in Gauzy —
Gauzy has no per-employee screenshot interval, no media-as-idle rule and no
per-department app productivity. The Angular page is a thin client over that
service, so adding a *setting* needs no Gauzy rebuild; only changing the *page*
does. The service verifies the caller's Gauzy token is a SUPER_ADMIN server-side;
the menu permission merely hides the link.

## Prerequisites (why this can't run on any machine)

- **~12 GB free RAM.** The Angular production build sets
  `--max-old-space-size=12288`. This box has 15 GB total but was showing ~4 GB
  free — **close other apps first** (Chrome, editors) or it will OOM/thrash.
- **~15 GB free disk** for `node_modules` + `dist`.
- **On mains power.** The build takes tens of minutes.
- **Node 24.17.0 — use the `.nvmrc` pin, not merely ">= 24".** `package.json`
  says `"engines": {"node": ">=24"}`, but that is not the binding constraint:
  a transitive dep (`@semantic-release/github`) demands
  `^22.14.0 || >= 24.10.0`, so Node 24.8.0 sits in the gap and fails just as
  hard as Node 22 does. Both failures read *"The engine node is incompatible"*.
  Match `.nvmrc` and the whole class of problem disappears. `yarn` is not installed globally and comes
  from `corepack`, whose shim is written into the **active Node version's** bin
  directory — so `corepack enable` must be re-run after switching Node, or
  `yarn` will be "command not found".

## Build + deploy

Run from the Gauzy checkout. Use `!` in the Claude prompt to run each in-session,
or a normal terminal.

```bash
cd ~/ever-gauzy

# 0. Apply the source changes (skip if already applied — they are, currently)
git apply ~/System-Tracker/dashboard-mods/gauzy-dashboard.patch   # if starting clean

# 1. Select Node >= 24, THEN get yarn — corepack writes its shim into the
#    active version's bin dir, so this order matters.
source "$HOME/.nvm/nvm.sh" && nvm install 24.17.0 && nvm use 24.17.0
corepack enable && corepack prepare yarn@1.22.22 --activate

# 2. Install deps — large, one-time, ~10-20 min
yarn install

# 3. Production build of the web app — the heavy step (~12 GB RAM, tens of min)
NODE_OPTIONS=--max-old-space-size=12288 yarn build:gauzy:prod
#   output -> dist/apps/gauzy

# 4. Deploy: replace the served bundles in the running webapp container.
#    No image rebuild needed — nginx serves /srv/gauzy.
docker exec webapp sh -c 'rm -rf /srv/gauzy_old && cp -r /srv/gauzy /srv/gauzy_old'   # backup
docker cp dist/apps/gauzy/. webapp:/srv/gauzy/

# 5. Hard-reload the browser (Ctrl+Shift+R). Done.
```

## Verify

- Header **start/stop timer widget is gone**.
- **"Worked today"** counts up every second.
- Data refreshes on its own within ~60s (no manual Refresh).

## Rollback

```bash
docker exec webapp sh -c 'rm -rf /srv/gauzy && mv /srv/gauzy_old /srv/gauzy'
# and to drop the source edits:
cd ~/ever-gauzy && git checkout -- \
  packages/ui-core/shared/src/lib/time-tracker/time-tracker/time-tracker.component.html \
  packages/plugins/dashboard-time-track-angular-ui/src/lib/components/time-tracking/time-tracking.component.ts \
  packages/plugins/dashboard-time-track-angular-ui/src/lib/components/time-tracking/time-tracking.component.html
```

## AGPL note

Ever Gauzy is AGPL-3.0. These are source modifications: if you expose this
modified Gauzy to users outside the company you must offer them the modified
source (AGPL §13) and rebrand off the "Ever"/"Gauzy" marks. Internal-only use is
fine. The changes are isolated to three component files and reverted cleanly by
`git checkout` above.
