# Serving the dashboard and API from one URL

**Status: proposal, not yet done.** Everything here is grounded in the files
named, but the production Docker path has never been exercised with our changes
— locally we run `ng build --configuration development` behind a small static
server. Expect to iterate once or twice on the first deploy.

## 1. Why there are two ports today

| Port | What it is | Serves |
|---|---|---|
| `4200` | the dashboard | static files only — no data, no logic |
| `3000` | the API (`apps/api`) | every figure the dashboard shows, and every tracker post |

The dashboard holds nothing. Each page load fetches from `:3000`, which is the
only thing that talks to Postgres. The trackers post there too, every 60
seconds. Two ports means two origins, which means CORS, which means
`CLIENT_BASE_URL` has to be right or the dashboard loads and then shows nothing.

## 2. What one URL looks like

Two services still, but only one is reachable from outside:

```
                    ┌──────────────────────────────────────┐
  browser ─────────►│  webapp  (public)                    │
  tracker ─────────►│    nginx                             │
                    │      /       → static dashboard      │
                    │      /api/   → proxy ──┐             │
                    └────────────────────────┼─────────────┘
                                             ▼   private network
                                       ┌───────────┐   ┌──────────┐
                                       │    api    │──►│ Postgres │
                                       └───────────┘   └──────────┘
```

Everything arrives on one hostname. `/api/...` is proxied internally and the
browser never sees a second origin.

What that removes:

- **CORS entirely** — same origin, so `CLIENT_BASE_URL` stops being a way to
  break the page.
- **A second address to keep in step** — trackers and people use one URL.
- **Public reachability of the API** — it is only accessible through nginx.

## 3. The image already supports it

`.deploy/webapp/Dockerfile` produces an nginx image carrying **two** config
templates and **two** entrypoints. Which pair runs decides whether you get one
port or two:

| Entrypoint | Template used | `/api/` proxy? |
|---|---|---|
| `entrypoint.prod.sh` | `nginx.prod.conf` | **no** — static only |
| `entrypoint.compose.sh` | `nginx.compose.conf` | **yes** |

The compose template is the one we want:

```nginx
upstream api { server ${API_HOST}:${API_PORT}; }

server {
  listen 4200;
  location /     { root /srv/gauzy; try_files $uri $uri/ /index.html; }
  location /api/ { proxy_pass http://api; proxy_set_header Host $http_host; }
}
```

`entrypoint.compose.sh` fills `${API_HOST}` and `${API_PORT}` from the
environment, so **the API address is set at container start, not at build
time**. That also applies to the dashboard's own `API_BASE_URL`: the entrypoint
runs `replacements.sed` over the built JavaScript, rewriting the placeholders
inside the bundle before nginx starts. One image, any environment.

This corrects an assumption worth naming: `API_BASE_URL` is *not* compiled in.
It is for our local dev build, which is why `.env.local` matters here — but the
production image substitutes it at runtime.

## 4. What to change

### 4.1 Use the compose entrypoint

The default `CMD` runs `entrypoint.prod.sh`, which gives the static-only
config. Override the entrypoint to `./entrypoint.compose.sh`.

One caveat: that script ends with `./wait`, which blocks until
`$API_HOST:$API_PORT` answers. Good for ordering, but if the API is slow to
start the webapp container sits waiting and a platform health check may kill it
first. If that happens, either raise the health-check grace period or drop the
`./wait` line in a copy of the script.

### 4.2 Point the upstream at the API's private address

| Variable | Value |
|---|---|
| `API_HOST` | the API service's internal hostname (Railway supplies one, e.g. `api.railway.internal`) |
| `API_PORT` | `3000` |

No code change — these are the variables the template already interpolates.

### 4.3 Set the dashboard's own URLs to the single origin

| Variable | Value |
|---|---|
| `API_BASE_URL` | the one public URL (`https://tracker.example.com`) |
| `CLIENT_BASE_URL` | the same URL |

Both are the same because there is now only one origin. Requests go to
`https://tracker.example.com/api/...`, which nginx proxies onward.

### 4.4 Do not give the API a public domain

On Railway a service is only reachable externally if you attach a domain. Leave
the API without one. It stays on the private network, reachable by the webapp
and nothing else.

### 4.5 Repoint every tracker

Each workstation's `tracker/config.json` (or the `GAUZY_URL` env var) still says
`http://localhost:3000`. Until changed, trackers post nowhere useful — and will
do so **silently**, because the tracker is written to treat a failed post as a
transient error and carry on. Set:

```json
{ "gauzy_url": "https://tracker.example.com" }
```

The tracker appends `/api/...` itself, so the base URL is all it needs.

## 5. Order of work

1. Deploy **Postgres** first; nothing works without it.
2. Deploy the **API**, no public domain. Confirm it is healthy from the webapp
   container, not from your laptop — it should *not* be reachable from outside.
3. Deploy the **webapp** with the compose entrypoint and the variables above.
4. Open the one URL, log in, confirm the Productivity page draws.
5. Repoint **one** tracker, watch a slot arrive, then do the rest.

Step 4 before step 5 matters: if the dashboard is broken you want to be
debugging one thing, not a fleet of trackers as well.

## 6. Two things to settle first

**AGPL §13.** Gauzy is AGPL-3.0 and we are deploying a *modified* copy — the
manager scoping, My work page, tracker settings and productivity work are all
changes to it. Serving that to users over a network triggers §13: the modified
source must be offered to those users, and the "Ever"/"Gauzy" marks need
removing if this is presented as our own product. Internal-only use is the
simpler position. This is already recorded in `.claude/CLAUDE.md` and is a
decision to make before deploying, not after.

**The trackers reach a public URL now.** Today they post to `localhost` on the
same machine. After this they authenticate over the internet with credentials in
a `0600` file on each workstation. Worth deciding whether each machine gets its
own employee account — `docs/HANDOVER.md` already flags that they currently
share `admin@ever.co`, which is a poor arrangement locally and a worse one over
the network.

## 7. If you would rather keep two URLs

Nothing above is required. Two public services also work — it is what
`render.yaml` describes, and it is the arrangement Ever ship by default. The
cost is CORS: `CLIENT_BASE_URL` on the API must exactly match the dashboard's
origin, and when it does not, the symptom is a dashboard that loads and then
shows no data — indistinguishable at a glance from a broken database.
