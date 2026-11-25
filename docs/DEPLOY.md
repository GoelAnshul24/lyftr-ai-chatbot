# Deployment guide

Backend: **Railway** (Docker service + persistent volume). Frontend: **Vercel**.
Deploy the backend first, then the frontend, then go back and allow the frontend's origin in the backend.

> Honest status: I could not deploy these myself (no accounts here). The platform facts below were checked
> against the platforms' docs; the click-paths may differ slightly if their UI changed. The app itself was
> verified locally with `make up` and the post-deploy `smoke.sh`.

## Why Railway (and what each platform does with the SQLite file)

| Platform | Persistent disk for SQLite? |
|---|---|
| **Railway** (recommended) | Yes. Volumes are available on the Trial and Hobby plans. Trial is a one-time $5 credit with a small (0.5 GB) volume; Hobby is $5/month. A volume survives restarts and redeploys. |
| Render | **Not on the free tier.** Free web services have an ephemeral filesystem (the SQLite file is wiped on every restart, redeploy and idle spin-down) and cannot attach a disk. A persistent Disk needs a paid instance. |
| Fly.io | Volumes exist, but new organizations get no free tier (a small trial credit only), so it is paid in practice. |

If you deploy on a platform without a disk, the app still works (the schema is created on startup), but chat
history is lost whenever the container restarts. The cache is in-memory, so it is also emptied on every restart
on any platform.

## 1. Backend on Railway

1. Push the repo to GitHub (public). Make sure `.env` is **not** in it (`.gitignore` already excludes it).
2. railway.com → **New Project** → **Deploy from GitHub repo** → pick your repo.
3. Open the new service → **Settings** → **Source** → set **Root Directory** to `/backend`.
   Railway finds `backend/Dockerfile` (capital D) and builds it.
4. **Variables** tab → add these (do not set `PORT`: Railway injects it and the container honors it):

   | Variable | Value |
   |---|---|
   | `LLM_API_KEYS` | `your_key_1,your_key_2` (real Gemini keys, comma-separated, no spaces, from two different Google projects if you can) |
   | `DATABASE_URL` | `sqlite:////data/app.db` (four slashes: the path is `/data/app.db`) |
   | `ALLOWED_ORIGINS` | `http://localhost:3000` for now; you will add the Vercel URL in step 3 below |
   | `ENABLE_FAILURE_SIMULATION` | `true` (required by the assignment on the deployed backend) |
   | `LLM_MODEL` | `gemini/gemini-3.5-flash-lite` |
   | `RAILWAY_RUN_UID` | `0` (Railway mounts volumes as root; our image runs as a non-root user, so without this SQLite cannot write to `/data` and you get "permission denied") |

   Optional: `DEFAULT_SYSTEM_PROMPT`, `LLM_TIMEOUT` (seconds, default 30).
5. Add the volume: on the project canvas press **Ctrl/Cmd+K** → **New Volume** (or right-click the canvas →
   **Volume**), attach it to the backend service, and set the **Mount Path** to `/data`.
6. Service → **Settings** → **Deploy** → **Healthcheck Path** = `/health`. Give it a generous timeout
   (e.g. 120 s): the first start imports LiteLLM. `/health` returns 503 until the DB is reachable **and** at
   least 2 keys are set, so a deploy with a missing key will correctly be reported as failed.
7. Service → **Settings** → **Networking** → **Generate Domain**. Copy the URL, e.g.
   `https://lyftr-backend-production.up.railway.app` (no trailing slash).
8. Check it:
   ```bash
   curl https://YOUR-BACKEND-URL/health
   # {"status":"ok","keys_configured":2,"cache_enabled":true}
   ```
9. Check the volume really persists: send a chat (smoke test below), click **Redeploy** on the service, then
   `GET /sessions/<id>/messages` for the same session. The history should still be there.

## 2. Frontend on Vercel

1. vercel.com → **Add New… → Project** → import the same GitHub repo.
2. **Root Directory**: `frontend`. **Framework Preset**: Vite (auto-detected). Build command `npm run build`,
   output directory `dist` (already in `frontend/vercel.json`, which also adds the SPA rewrite so any path serves
   `index.html`).
3. **Environment Variables** → `VITE_API_URL` = your Railway URL, e.g.
   `https://lyftr-backend-production.up.railway.app` (no trailing slash). This is read **at build time**, so if
   you change it later you must **redeploy** the frontend.
4. **Deploy**. Copy the production URL, e.g. `https://lyftr-chatbot.vercel.app`.

## 3. Allow the frontend origin in the backend (CORS)

Back in Railway → backend **Variables** → set

```
ALLOWED_ORIGINS=https://lyftr-chatbot.vercel.app,http://localhost:3000
```

Rules: exact origin match, no trailing slash, no wildcard. Vercel *preview* deployments have different URLs and
will be blocked unless you add them too. Railway redeploys automatically after a variable change.

## 4. Smoke test the live system

```bash
./smoke.sh https://YOUR-BACKEND-URL
```

All lines should print `PASS`. Then open the Vercel URL, send a message, and confirm the metadata appears. The
browser Network tab should show calls to your Railway URL with no CORS errors.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Deploy fails its healthcheck; `/health` says "key pool not ready" | `LLM_API_KEYS` has fewer than 2 keys. |
| `/health` says "database unreachable" or logs show `unable to open database file` / permission denied | Volume not mounted at `/data`, or `RAILWAY_RUN_UID=0` missing. |
| Browser shows "Cannot reach the server" or a CORS error | `ALLOWED_ORIGINS` is missing the exact Vercel origin, or `VITE_API_URL` was wrong at build time (redeploy the frontend). |
| Chat returns 503 "all providers unavailable" | Both keys are rate limited or out of quota. Gemini's free tier has daily limits; both keys from the same Google project share one quota. |
| Failover header does nothing | `ENABLE_FAILURE_SIMULATION` is not exactly `true`. |
