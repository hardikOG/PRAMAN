# DEPLOYMENT.md — free-tier demo hosting

This deploys PRAMAN's actual application architecture — the same FastAPI
app, the same React console, the same portable SQLAlchemy models — onto
free-tier infrastructure for a public demo. It is **not** a production
deployment target: Render's free Postgres expires after 30 days and free
Key Value (Redis-compatible) is in-memory and loses state on every
restart. Call this what it is — production-grade application architecture
deployed on free-tier infrastructure for demonstration — not "production
infrastructure."

I (the assistant) did not create any accounts or click deploy on your
behalf — creating accounts and entering credentials on third-party services
isn't something I do. Everything below is exact enough to copy-paste once
you're logged into your own Render account.

## What gets deployed where

```
Render Static Site   →  apps/web (React/Vite console)
Render Web Service    →  apps/api (FastAPI, built from docker/Dockerfile.api)
Render Postgres       →  DATABASE_URL (replaces local SQLite)
Render Key Value      →  REDIS_URL (replaces local fake://local)
```

The MCP storefront (`apps/mcp_storefront/server.py`) and the worker
(`apps/api/worker.py`) are not required for the console demo (the
Playground calls `authorize()` directly, same as `praman demo`) — skip
deploying those unless you specifically want to demo an MCP client talking
to the storefront over the network. If you do, they're a second and third
Render Web Service, same Dockerfile, different start commands (see below).

## 1. Render Postgres

Dashboard → New → PostgreSQL. Any name/region; free tier.

Render gives you a connection string that looks like:

```
postgresql://praman_user:xxxxx@dpg-xxxxx.render.com/praman_db
```

**This needs one edit before it works with this codebase**: SQLAlchemy's
async engine needs the `asyncpg` driver named explicitly in the scheme.
Change `postgresql://` to `postgresql+asyncpg://` — otherwise
`create_async_engine` raises immediately on startup (`get_engine()`,
`apps/api/db.py`, is synchronous-driver-agnostic but the project only
installs the async driver). Keep everything else in the string unchanged.

## 2. Render Key Value

Dashboard → New → Key Value. Free tier. Copy the internal connection
string it gives you (starts `redis://` or `rediss://`) — use the *internal*
one if your web service is in the same Render region, it's faster and
doesn't count against any external bandwidth limits.

No edits needed: `redis.asyncio.from_url()` (`apps/api/redis_client.py`)
accepts this directly.

## 3. Render Web Service (the API)

Dashboard → New → Web Service → connect this repo.

- **Runtime**: Docker
- **Dockerfile path**: `docker/Dockerfile.api`
- **Docker context**: repo root (`.`)
- **Start command**: leave blank — the Dockerfile's own `CMD` already
  binds `uvicorn` to `0.0.0.0:8000`. **Do not hardcode `--port 8010`** (the
  local-dev port, chosen only because this dev machine already had other
  things on 8000) — Render assigns its own port via the `$PORT` env var and
  routes traffic to it. Override the Dockerfile's `CMD` with:

  ```
  uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT
  ```

  as the service's explicit start command, since `$PORT` isn't known at
  image-build time and can't be baked into the Dockerfile's `CMD` array.

- **Environment variables** (Render dashboard → Environment):

  | Key | Value |
  |---|---|
  | `DATABASE_URL` | the edited (`+asyncpg`) Postgres string from step 1 |
  | `REDIS_URL` | the Key Value string from step 2 |
  | `PRAMAN_ENV` | `prod` |
  | `LOG_LEVEL` | `INFO` |
  | `ANTHROPIC_API_KEY` | optional — live faithfulness adjudication; offline heuristic runs without it |
  | `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | optional — Razorpay **test mode** keys; `DeterministicExecutor` runs without them (see `apps/api/payments/__init__.py`'s automatic fallback) |
  | `PAYMENT_EXECUTOR` | `razorpay` (safe either way — falls back to deterministic if the two keys above aren't set) |
  | `LEDGER_SIGNING_KEY_PATH` | `.keys/ledger_ed25519.pem` |

  Mark `ANTHROPIC_API_KEY` and the two `RAZORPAY_*` values as **secret**
  environment variables in Render's dashboard — never put them in a
  committed file. `.env` is already gitignored; this repo's `.env.example`
  has no real values in it, only placeholders.

- **Health check path**: `/health`

**A real gap to know about**: the ledger signing key
(`load_or_create_signing_key`, `apps/api/ledger/crypto.py`) is generated on
first use and written to `.keys/ledger_ed25519.pem` — but Render's free web
services have an *ephemeral filesystem*: a redeploy or restart wipes it,
generating a *new* key, which makes every previously-issued proof bundle's
signature unverifiable against the new public key. For a demo this is
usually fine (you seed + demo fresh each session), but if you want key
continuity across restarts, generate one key locally
(`python -m apps.api.cli seed`), then paste its PEM contents into a Render
**Secret File** mounted at `.keys/ledger_ed25519.pem` instead of letting
the app generate one on the ephemeral disk.

## 4. Render Static Site (the console)

Dashboard → New → Static Site → connect this repo.

- **Root directory**: `apps/web`
- **Build command**: `npm install && npm run build`
- **Publish directory**: `dist`
- **Environment variable**: `VITE_API_BASE_URL` = the API service's public
  URL from step 3 (e.g. `https://praman-api.onrender.com`) — Vite bakes
  this in at *build* time (`apps/web/src/api.ts` reads
  `import.meta.env.VITE_API_BASE_URL`), so set it before the first build,
  not after.

## 5. CORS

`apps/api/main.py` currently allows every origin (`allow_origins=["*"]`) —
written for local dev where the console is always Vite on `localhost`. This
already works against a deployed static site with no code change (a
wildcard origin permits any caller, including your Render static site's
own domain), so nothing to do here for the demo to function. Tightening
this to the static site's exact origin is a reasonable follow-up if this
ever runs somewhere that isn't a judged internship demo.

## 6. First request will be slow — and that's expected, not broken

Render's free web services spin down after 15 minutes idle; the next
request wakes it, which can take 30–60 seconds. If you're demoing live,
either hit the API's `/health` endpoint a minute before you start talking,
or add a visible "waking up" state to the console so a judge doesn't think
it's hung. (Not implemented in this codebase — a small, honest addition if
you want it: a `Playground.tsx` loading state that reads "Connecting to
PRAMAN Gateway… may take up to a minute on free infrastructure" instead of
just a spinner, shown while the very first `/playground/presets` call is
in flight.)

## Checklist

- [ ] Render Postgres created, connection string edited to `postgresql+asyncpg://`
- [ ] Render Key Value created
- [ ] Render Web Service deployed (Docker, `docker/Dockerfile.api`, start
      command overridden to use `$PORT`)
- [ ] API env vars set (`DATABASE_URL`, `REDIS_URL`, at minimum)
- [ ] `GET https://<api-service>.onrender.com/health` returns `{"status":"ok"}`
- [ ] `POST https://<api-service>.onrender.com/playground/run` with
      `{"preset": "honest"}` returns an ALLOW decision — this exercises DB
      write, Redis write, and (deterministic) payment capture in one call
- [ ] Render Static Site deployed with `VITE_API_BASE_URL` pointed at the
      API service, built *after* that env var was set
- [ ] Console loads at the static site's URL and the Playground runs all
      three demo-script presets (Honest purchase / Cart substitution
      (size) / Uncertain — needs a human) end to end, including the
      "Confirm as human" step
