"""HTTP API for the final UI (design doc 7.2), serving ui/web on the same origin.

    .venv/bin/uvicorn --factory app.server:create_app --port 8000
    PHILOCAFE_FAKE=1 .venv/bin/uvicorn --factory app.server:create_app --port 8000   # offline stand-ins

Add --host 0.0.0.0 to reach it from a phone on the same Wi-Fi (the PWA). Anyone on
that network can then use the app, and so spend your API credit; keep it to demos.

On Vercel (ADR-11) the entrypoint is asgi.py and these environment variables matter:
- PHILOCAFE_ACCESS_CODE: every API request must carry it in X-Philocafe-Code.
- PHILOCAFE_CHECKPOINT_URL, else DATABASE_URL or POSTGRES_URL: conversation checkpoints
  go to Postgres, so a thread (and its support mode, FR-32) survives across function
  instances. Without one, checkpoints stay in memory, which is right for local runs.
- CRON_SECRET: guards /internal/purge, which the daily Vercel Cron calls to delete
  conversations older than PHILOCAFE_RETENTION_HOURS: 168 (7 days) by default, set to
  24 on showcase day; 0 turns the purge off.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.config import ROOT
from app.deps import Deps
from app.graph import build_graph, run_turn

log = logging.getLogger(__name__)

MAX_TEXT = 2000
DEFAULT_RETENTION_HOURS = 168     # 7 days, for multi-day testing; 24 on showcase day (ADR-11)
WEB_DIR = ROOT / "ui" / "web"
CODE_HEADER = "x-philocafe-code"
mimetypes.add_type("application/manifest+json", ".webmanifest")


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"


def deps_from_env() -> Deps:
    if os.environ.get("PHILOCAFE_FAKE") == "1":
        from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps, fake_distill_note
        return fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")], delay=0.03),
                         distill_note=fake_distill_note)
    from app import retrieval
    from app.deps import default_deps
    deps = default_deps()
    retrieval.retrieve(deps.config.default_persona, "warm up", k=1)   # load the embedder before the first turn
    return deps


def checkpoint_url() -> str | None:
    for name in ("PHILOCAFE_CHECKPOINT_URL", "DATABASE_URL", "POSTGRES_URL"):
        if os.environ.get(name):
            return os.environ[name]
    return None


def postgres_checkpointer(url: str):
    """LangGraph's Postgres checkpointer on a small pool. Prepared statements are off so
    a transaction-mode pooler (such as Neon's) works."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(conninfo=url, min_size=0, max_size=4, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()            # idempotent: creates or migrates the checkpoint tables
    return saver


def stale_threads(saver, hours: float) -> list[str]:
    """Threads whose newest checkpoint is older than `hours`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with saver._cursor() as cur:
        rows = cur.execute("SELECT thread_id FROM checkpoints GROUP BY thread_id "
                           "HAVING max(checkpoint->>'ts') < %s", (cutoff,)).fetchall()
    return [r["thread_id"] for r in rows]


def create_app(deps: Deps | None = None, checkpointer=None, access_code: str | None = None) -> FastAPI:
    deps = deps or deps_from_env()
    if checkpointer is None and (url := checkpoint_url()):
        checkpointer = postgres_checkpointer(url)
    graph = build_graph(deps, checkpointer=checkpointer)
    code = access_code if access_code is not None else os.environ.get("PHILOCAFE_ACCESS_CODE", "")

    def locked(request: Request) -> JSONResponse | None:
        if code and not hmac.compare_digest(request.headers.get(CODE_HEADER, ""), code):
            return error(401, "access_code", "This café needs an access code.")
        return None

    def thread_state(thread_id: str) -> dict:
        return graph.get_state({"configurable": {"thread_id": thread_id}}).values

    async def personas(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        return JSONResponse([{"id": p.id, "name": p.name, "era": p.era, "tagline": p.tagline,
                              "avatar_url": f"assets/mono_{p.id}.png", "available": True}
                             for p in deps.personas.values()])

    async def new_thread(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        return JSONResponse({"thread_id": uuid.uuid4().hex}, status_code=201)

    async def messages(request: Request):
        if denied := locked(request):
            return denied
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return error(400, "bad_json", "The request body is not JSON.")
        text = str(body.get("text") or "").strip()
        persona_id = str(body.get("persona_id") or deps.config.default_persona)
        if not text:
            return error(400, "empty_text", "The message is empty.")
        if len(text) > MAX_TEXT:
            return error(400, "text_too_long", f"Messages are limited to {MAX_TEXT} characters.")
        if persona_id not in deps.personas:
            return error(404, "unknown_persona", f"No persona {persona_id!r}.")
        events = run_turn(graph, request.path_params["thread_id"], text, persona_id)
        return StreamingResponse((sse(e) for e in events), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    async def note(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        state = thread_state(request.path_params["thread_id"])
        if not state.get("messages"):
            return error(404, "unknown_thread", "No conversation in this thread yet.")
        if state.get("mode") == "support":
            return error(409, "support_mode", "Notes are not made from a paused conversation.")
        if deps.distill_note is None:
            return error(501, "notes_unavailable", "Notes are not set up on this server.")
        persona = deps.personas.get(state.get("persona_id", ""))
        try:
            result = await run_in_threadpool(deps.distill_note, persona.name if persona else "the philosopher",
                                             state["messages"])
        except Exception as e:
            return error(502, "note_failed", type(e).__name__)
        return JSONResponse(result)

    async def purge(request: Request) -> JSONResponse:
        # Vercel Cron sends "Authorization: Bearer $CRON_SECRET".
        secret = os.environ.get("CRON_SECRET", "")
        if not secret or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {secret}"):
            return error(401, "cron_only", "Only the scheduled purge may call this.")
        hours = float(os.environ.get("PHILOCAFE_RETENTION_HOURS") or DEFAULT_RETENTION_HOURS)
        if hours <= 0:
            return JSONResponse({"deleted": 0, "note": "PHILOCAFE_RETENTION_HOURS=0: purge is off"})
        if not hasattr(checkpointer, "delete_thread") or not hasattr(checkpointer, "conn"):
            return JSONResponse({"deleted": 0, "note": "checkpoints are in memory"})
        threads = await run_in_threadpool(stale_threads, checkpointer, hours)
        for thread_id in threads:
            await run_in_threadpool(checkpointer.delete_thread, thread_id)
        log.info("purged %d conversations older than %s hours", len(threads), hours)
        return JSONResponse({"deleted": len(threads)})

    routes = [Route("/personas", personas),
              Route("/threads", new_thread, methods=["POST"]),
              Route("/threads/{thread_id}/messages", messages, methods=["POST"]),
              Route("/threads/{thread_id}/note", note, methods=["POST"]),
              Route("/internal/purge", purge)]
    # The same mount on Vercel: it promotes StaticFiles mounts to its CDN at build time, and the
    # function serves the files itself if it does not. Declared last, so the API routes win.
    if WEB_DIR.exists():
        routes.append(Mount("/", StaticFiles(directory=WEB_DIR, html=True)))
    return FastAPI(routes=routes, docs_url=None, redoc_url=None, openapi_url=None)
