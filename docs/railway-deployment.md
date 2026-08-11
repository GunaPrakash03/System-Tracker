# Deploying to Railway — one public URL

**Status: runbook, not yet exercised.** Everything here is grounded in the files
named and in Railway's platform behaviour, but no deploy has been run against it.
Expect to iterate once or twice on the first attempt. The topology is the one
proposed in `docs/single-endpoint-deployment.md`; this document is the Railway
implementation of it.

## 1. The shape

Three Railway services, **one of which is reachable from outside**:

```
                    ┌──────────────────────────────────────┐
  browser ─────────►│  webapp  (public domain)             │
  tracker ─────────►│    nginx, listening on 4200          │
                    │      /       → static dashboard      │
                    │      /api/   → proxy ──┐             │
                    └────────────────────────┼─────────────┘
                                             ▼  private network (IPv6)
                                       ┌───────────┐   ┌──────────┐
                                       │    api    │──►│ Postgres │
                                       │ no domain │   │  volume  │
                                       └───────────┘   └──────────┘
```

Users and trackers know exactly one hostname. `/api/...` is proxied internally,
the browser never sees a second origin, and there is no CORS to get wrong.

**Why the API is a separate service rather than the same container.** Nothing
about "one URL" requires one process — the second service simply has no public
domain, so it does not exist as far as the outside world is concerned. Putting
nginx and Node in one container would buy no user-visible simplification and
would cost a custom ~3.4 GB image to maintain, a shared memory limit, and an API
restart that takes the dashboard down with it.

## 2. Before anything: the images are yours, not Ever's

Two facts decide the whole build strategy.

**The published images will not do.** Our customisations touch `packages/core`
and `packages/contracts` — manager scoping, the time-slot and activity services,
per-employee settings on the employee model (see `dashboard-mods/README.md`,
rows 8–10). `ghcr.io/ever-co/gauzy-api` does not contain them. Both images must
be built from the vendored tree in `gauzy/`. This also means
`render.yaml` in the Gauzy tree is **not** a template to copy: it deploys Ever's
demo images.

**Railway should not be the one building them.** The Angular production build
asks for a great deal of memory — `.deploy/webapp/Dockerfile` defaults
`NODE_OPTIONS` to `--max-old-space-size=30000`, and our own local build runbook
pins it to 12 GB — and it runs for tens of minutes. Build locally, where the
constraints are already known and satisfied, push to a registry, and have Railway
deploy **by image**. That also keeps deploys fast, because a redeploy is a pull
rather than a monorepo build.

Sizes to expect, measured locally: the API image is **~3.4 GB**, the webapp image
**~98 MB** (it is just nginx plus the compiled bundle).

## 3. Build and push the images

From `gauzy/` in this repo — the vendored Gauzy tree. BuildKit is required, as
both Dockerfiles use `RUN --mount` stage bind mounts.

```bash
cd ~/System-Tracker/gauzy

REG=ghcr.io/<your-org>          # or any registry Railway can pull from
TAG=$(git rev-parse --short HEAD)

docker buildx build -f .deploy/api/Dockerfile \
  --build-arg NODE_ENV=production \
  --build-arg GAUZY_APP_COMMIT=$TAG \
  -t $REG/tracker-api:$TAG -t $REG/tracker-api:latest --load .

docker buildx build -f .deploy/webapp/Dockerfile \
  --build-arg NODE_ENV=production \
  --build-arg NODE_OPTIONS=--max-old-space-size=12288 \
  --build-arg GAUZY_APP_COMMIT=$TAG \
  -t $REG/tracker-webapp:$TAG -t $REG/tracker-webapp:latest --load .

docker push $REG/tracker-api:$TAG   && docker push $REG/tracker-api:latest
docker push $REG/tracker-webapp:$TAG && docker push $REG/tracker-webapp:latest
```

The same host prerequisites as any local Gauzy build apply — roughly 12 GB free
RAM and 15 GB free disk, on mains power. `.dockerignore` excludes `node_modules`
and `dist`, so the build context is source only.

If the registry is private, Railway needs credentials: **service → Settings →
Source → Docker image**, with username and token.

**Tag with the commit, deploy the commit tag, not `latest`.** Railway caches by
digest and a moved `latest` is the classic way to spend an afternoon debugging a
deploy that silently shipped the previous build — the same failure mode as
copying over `/srv/gauzy` instead of replacing it (`dashboard-mods/README.md`).

## 4. Postgres — restore, don't start empty

Add Railway's Postgres, and give it a volume.

Then **restore the existing database into it** rather than letting a fresh API
seed one. The local DB already holds the organisation, tenant and employee
records whose IDs are recorded in `docs/HANDOVER.md` §7, the feature toggles
applied by `config/minimal-tracking-features.sql`, the role changes from
`config/roles-manager-hr.sql`, and every time slot collected so far. Seeding
fresh throws all of that away and hands you new IDs.

```bash
docker exec -i db pg_dump -U postgres -Fc gauzy > gauzy.dump

# restore over Railway's public Postgres endpoint (Railway → Postgres → Connect)
pg_restore --no-owner --no-privileges -d "$RAILWAY_PG_URL" gauzy.dump
```

`--no-owner --no-privileges` matters: Railway's Postgres user is not `postgres`,
and without these the restore fails on every `ALTER ... OWNER TO`.

After restoring, keep `DB_SYNCHRONIZE=false` on the API. A schema-syncing API
pointed at a restored production database is a bad combination.

## 5. The API service — no public domain

Deploy from `$REG/tracker-api:<tag>`. **Do not attach a domain.** On Railway a
service is reachable externally only if one is attached; leaving it off is what
keeps the API private.

Variables. The first three are the ones that cause silent, confusing failures,
so they come first:

| Variable | Value | Why |
|---|---|---|
| `DB_TYPE` | `postgres` | **The image bakes `DB_TYPE=better-sqlite3`.** Left alone, the API silently serves a seeded demo database — no real organisation, every sidebar feature on, foreign timezones on screenshots. Three unrelated-looking bugs, one cause (`docs/HANDOVER.md` §9.2). |
| `TZ` | `UTC` | The timestamp columns are `timestamp without time zone` holding UTC, and node-postgres parses them in the *process* timezone. Under IST every time served is 5½ hours out (§9.2). |
| `API_HOST` | `::` | Railway's private network is **IPv6-only**. The image default `0.0.0.0` binds IPv4 only, so the webapp's proxy cannot reach the API at all — the dashboard loads and shows nothing. The value feeds `app.listen(port, host)` directly (`packages/core/src/lib/bootstrap/index.ts:213`). Verify this on the first deploy. |
| `API_PORT` | `3000` | |
| `DB_HOST` | `${{Postgres.PGHOST}}` | Railway variable reference — resolves to the private hostname |
| `DB_PORT` | `${{Postgres.PGPORT}}` | |
| `DB_NAME` | `${{Postgres.PGDATABASE}}` | |
| `DB_USER` | `${{Postgres.PGUSER}}` | |
| `DB_PASS` | `${{Postgres.PGPASSWORD}}` | |
| `DB_SSL_MODE` | `false` | Private-network traffic; no TLS to terminate |
| `DB_SYNCHRONIZE` | `false` | See §4 |
| `API_BASE_URL` | the one public URL | e.g. `https://tracker.up.railway.app` |
| `CLIENT_BASE_URL` | the same URL | Same origin now — this is the variable that, when wrong, produces a dashboard that loads and then shows no data |
| `ALLOWED_ORIGINS` | the same URL | |
| `NODE_ENV` | `production` | |
| `IS_DOCKER` | `true` | Selects `assetPublicPath=/srv/gauzy/apps/api/public` (`packages/config/src/lib/default-config.ts:24`) — the path §6 mounts a volume at |
| `FILE_PROVIDER` | `LOCAL` | With the volume below. S3/Wasabi is the alternative if you would rather not carry a volume |
| `JWT_SECRET` | a fresh random value | **Not** `secretKey`. `render.yaml` ships the defaults; they are public knowledge and they mint valid tokens |
| `JWT_REFRESH_TOKEN_SECRET` | a fresh random value | Not `refreshSecretKey` |
| `EXPRESS_SESSION_SECRET` | a fresh random value | Not `gauzy` |
| `SENTRY_DSN` | *(empty)* | Already decided — `docs/HANDOVER.md` §7. Leaving it unset keeps API exceptions, which carry request payloads and employee IDs, inside the organisation |

**Volume:** mount one at `/srv/gauzy/apps/api/public`. Under `FILE_PROVIDER=LOCAL`
this is where uploads and screenshots are written; a container filesystem on
Railway is ephemeral, so without a volume every screenshot vanishes on redeploy.

**Health check path:** `/api/health`.

## 6. The webapp service — the public one

Deploy from `$REG/tracker-webapp:<tag>`, attach the domain, and set the **target
port to 4200** (Settings → Networking). `nginx.compose.conf` hardcodes
`listen 4200`; Railway's injected `PORT` is not consulted.

| Variable | Value |
|---|---|
| `API_HOST` | the API service's private hostname, e.g. `api.railway.internal` |
| `API_PORT` | `3000` |
| `API_BASE_URL` | the one public URL |
| `CLIENT_BASE_URL` | the same URL |

`API_BASE_URL` is **not** compiled into the bundle. The entrypoint runs
`replacements.sed` over the built JavaScript at every container start, so one
image serves any environment.

### The entrypoint, which needs a custom start command

The image's `CMD` runs `entrypoint.prod.sh`, which uses `nginx.prod.conf` —
static files only, **no `/api/` proxy**. The single-origin arrangement needs
`entrypoint.compose.sh` and `nginx.compose.conf` instead.

Railway's custom start command overrides `CMD`, not `ENTRYPOINT`. That happens to
be exactly enough, because `entrypoint.prod.sh` is a pass-through — its last line
is `exec "$@"`. So set the start command to:

```
./entrypoint.compose.sh nginx -g "daemon off;"
```

`entrypoint.prod.sh` execs it, the compose entrypoint does the bundle
substitution and writes the proxying nginx config, then execs nginx.

**If the container is killed during startup**, the cause is the `./wait` on the
last line of `entrypoint.compose.sh`, which blocks until `$API_HOST:$API_PORT`
answers. Good for ordering, fatal if the health check's grace period expires
first. Either raise the grace period, or use a start command that does the same
work without waiting:

```
sh -c 'envsubst < replacements.sed > replacements_values.sed && sed -i -f replacements_values.sed *.js && envsubst "\$API_HOST \$API_PORT" < /etc/nginx/conf.d/compose.conf.template > /etc/nginx/nginx.conf && exec nginx -g "daemon off;"'
```

The restricted variable list on the second `envsubst` is not optional — without
it, `envsubst` would also expand nginx's own `$uri` and `$http_host` to empty
strings and the config would be nonsense.

One consequence of dropping `./wait`: nginx resolves the `upstream` hostname at
startup and refuses to start if it does not resolve, so the webapp may crash-loop
until the API is up. Railway restarts it, and it settles — but deploy the API
first (§8) and it will not arise.

**Health check path:** `/`.

## 7. Repoint the trackers

Each workstation's `tracker/config.json`, or the `GAUZY_URL` environment variable,
still says `http://localhost:3000`. Until changed, trackers post nowhere useful —
and do so **silently**, because a failed post is treated as transient and the loop
carries on.

```json
{ "server_url": "https://tracker.example.com" }
```

The key is **`server_url`** (`tracker/proc_tracker.py:196`, `:1077`). The base URL
is all it needs; the tracker appends `/api/...` itself.

## 8. Order of work

1. **Postgres** first, with its volume, and restore the dump (§4). Nothing works
   without it.
2. **API**, no public domain. Confirm it is healthy *from the webapp container*,
   not from your laptop — it should not be reachable from outside at all.
3. **Webapp**, with the compose start command, the target port, and the variables
   above.
4. Open the one URL, log in, confirm the **Productivity** page draws and
   Employees → Activity → Screenshots shows images.
5. Repoint **one** tracker, watch a slot arrive, then do the rest.

Step 4 before step 5 matters: if the dashboard is broken you want to be debugging
one thing, not a fleet of trackers as well.

## 9. Two things to settle before deploying, not after

**AGPL §13.** Gauzy is AGPL-3.0 and this deploys a *modified* copy — the manager
scoping, My work page, tracker settings and productivity work are all changes to
it. Serving that to users over a network triggers §13: the modified source must
be offered to those users, and the "Ever"/"Gauzy" marks need removing if this is
presented as our own product. Internal-only use is the simpler position, and it
is a decision to make first.

**Credentials now cross the internet.** Today the trackers post to `localhost` on
the same machine. After this they authenticate over the public internet, and they
all currently share `admin@ever.co` / `admin` (`docs/HANDOVER.md` §7) — a poor
arrangement locally and a considerably worse one when the endpoint is public,
since those credentials are also a Super Admin login for the dashboard. Give each
workstation its own employee account and change the default password before the
domain goes live, not after.
