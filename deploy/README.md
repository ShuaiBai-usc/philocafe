# Deploying the café to Vercel (ADR-11)

The API runs as one Python function (entrypoint `asgi.py`, set in `pyproject.toml`), the web app
is served from Vercel's CDN (`public/`, written at build time), and conversation checkpoints live
in Postgres so a thread, and its support mode, survives across function instances.

## One-time setup

1. **Import the repository** in Vercel (New Project, then pick the GitHub repo). Leave the root at the
   repository root; Vercel detects the FastAPI app and runs `deploy/vercel_build.py` as the build step.
2. **Add Postgres**: Storage, then Neon (Marketplace). Pick a region near `sfo1` (for example AWS
   us-west-2). The integration sets `DATABASE_URL`; the server creates its tables on first start.
3. **Set environment variables** (Settings, then Environment Variables; never in the repo or the chat).
   `.env.example` lists the same names for local runs, where the deployment ones stay empty:

   | Name | Value |
   |---|---|
   | `ANTHROPIC_API_KEY` | Anthropic key (voice, fallback, translation, notes) |
   | `JEV_API_KEY` | TypeSafe key |
   | `PHILOCAFE_ACCESS_CODE` | the code you give the class; the app asks for it once per device |
   | `CRON_SECRET` | any long random string; guards the daily purge |
   | `PHILOCAFE_MIN_SCORE` | optional, defaults to 0.3 |
   | `PHILOCAFE_RETENTION_HOURS` | optional: 168 (7 days) by default; **set 24 on showcase day**; 0 = never purge |

4. **Deploy.** Branch pushes get preview deployments; `main` gets the production deployment. The daily
   purge (`vercel.json` crons) runs on production only and deletes conversations older than
   `PHILOCAFE_RETENTION_HOURS`. After changing that variable, redeploy so the function picks it up.

## Check a deployment

- `GET /personas` without the code returns 401; the page asks for the code, then shows **Live**.
- One message comes back with a citation, and the function logs show no `enable_load_extension` or
  sqlite-vec error. That error would mean Vercel's Python cannot load the vector extension; the corpus
  side (retrieval) would then need another plan.
- On an iPhone: open the URL in Safari, Share, Add to Home Screen.

## Build locally

`.venv/bin/python deploy/vercel_build.py` does what Vercel's build step does: builds `data/philocafe.db`,
caches the embedding model in `.cache/fastembed`, writes `ui/web/index.html` and copies the web app to
`public/` (all git-ignored).

## Limits worth knowing

- The function bundle is about 315 MB (Vercel's Python limit is 500 MB): keep Streamlit and pytest in
  `requirements-dev.txt`, not in `pyproject.toml`, which Vercel installs from.
- A cold start loads the embedding model; the first message after idle can take a few seconds longer.
- Anyone with the access code can spend the API budget; change the code to cut access.
