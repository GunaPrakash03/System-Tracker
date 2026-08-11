# Running the dashboard and API on one endpoint

One published port. nginx serves the dashboard at `/` and proxies `/api/` to the
API over the internal network, so browsers and trackers use a single origin,
there is no CORS to get wrong, and neither the API nor the database is reachable
from outside.

For Railway rather than a single host, see `docs/railway-deployment.md` — same
topology, same variables, different plumbing. The reasoning behind one URL is in
`docs/single-endpoint-deployment.md`.

## First run

```bash
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env          # it holds the DB password and the JWT secrets
$EDITOR deploy/.env            # fill in DB_PASS and the three secrets

cd deploy
docker compose up -d --build   # first build takes tens of minutes
```

Then open `http://localhost:8080`.

Generate each secret separately — `openssl rand -hex 32`. Do **not** reuse
Ever's published defaults (`secretKey`, `refreshSecretKey`, `gauzy`); they are
in `gauzy/render.yaml` and will mint valid tokens for anyone who tries them.

## The build is the slow part

`--build` compiles the Angular app from `gauzy/`, which needs roughly **12 GB of
free RAM** and runs for tens of minutes; the API image lands at ~3.4 GB. The
prerequisites are the same ones in `dashboard-mods/README.md`. Close Chrome and
editors first.

To skip building — on a small server, say — build the images once on a capable
machine, push them to a registry, and set `API_IMAGE` and `WEBAPP_IMAGE` in
`.env`. Then `docker compose up -d` pulls instead of building.

## What each service is for

| Service | Published? | Role |
|---|---|---|
| `st-webapp` | **yes**, `${PUBLIC_PORT}` → 4200 | nginx: static dashboard at `/`, proxy at `/api/` |
| `st-api` | no | every figure the dashboard shows, and every tracker post |
| `st-db` | no | Postgres, on a named volume |

`docker exec -i st-db psql -U postgres -d gauzy` for database access.

## Three variables that fail quietly

Set in `docker-compose.yml`, not `.env`, because getting them wrong produces
symptoms that look like other bugs entirely:

- **`DB_TYPE=postgres`** — the API image bakes `better-sqlite3`. Left alone it
  silently serves a seeded demo database: no real organisation, every sidebar
  feature on, foreign timezones on screenshots. Three unrelated-looking bugs,
  one cause (`docs/HANDOVER.md` §9.2).
- **`TZ=UTC`** — the timestamp columns are `timestamp without time zone` holding
  UTC, and node-postgres parses them in the process timezone. Under IST every
  time served is 5½ hours out.
- **`API_HOST`** — `0.0.0.0` here, but **`::` on Railway**, whose private network
  is IPv6-only. Bound to IPv4 only there, the proxy cannot reach the API and the
  dashboard loads showing nothing.

## Pointing the trackers at it

Each workstation's `tracker/config.json`, or `GAUZY_URL`:

```json
{ "server_url": "http://your-host:8080" }
```

The key is `server_url` (`tracker/proc_tracker.py:196`). The base URL is all it
needs — the tracker appends `/api/...` itself. Until this is changed the tracker
posts nowhere useful and does so **silently**, because a failed post is treated
as transient and the loop carries on.

Repoint one tracker first, watch a slot arrive, then do the rest.

## Data

Two named volumes, both of which matter:

- `db-data` — Postgres.
- `api-uploads` at `/srv/gauzy/apps/api/public` — screenshots and uploads under
  `FILE_PROVIDER=LOCAL`. Without it they vanish whenever the container is
  replaced.

Migrating an existing local instance? Dump and restore rather than starting
empty — a fresh seed discards the org, tenant and employee IDs recorded in
`docs/HANDOVER.md` §7, both SQL config files, and all history:

```bash
docker exec -i db pg_dump -U postgres -Fc gauzy > gauzy.dump
docker exec -i st-db pg_restore -U postgres --no-owner --no-privileges -d gauzy < gauzy.dump
```
