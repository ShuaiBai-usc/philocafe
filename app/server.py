"""HTTP API for the final UI (design doc 7.2), serving ui/web on the same origin.

    .venv/bin/uvicorn --factory app.server:create_app --port 8000
    PHILOCAFE_FAKE=1 .venv/bin/uvicorn --factory app.server:create_app --port 8000   # offline stand-ins

Add --host 0.0.0.0 to reach it from a phone on the same Wi-Fi (the PWA). Anyone on
that network can then use the app, and so spend your API credit; keep it to demos.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.config import ROOT
from app.deps import Deps
from app.graph import build_graph, run_turn

MAX_TEXT = 2000
WEB_DIR = ROOT / "ui" / "web"
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


def create_app(deps: Deps | None = None) -> Starlette:
    deps = deps or deps_from_env()
    graph = build_graph(deps)

    def thread_state(thread_id: str) -> dict:
        return graph.get_state({"configurable": {"thread_id": thread_id}}).values

    async def personas(request: Request) -> JSONResponse:
        return JSONResponse([{"id": p.id, "name": p.name, "era": p.era, "tagline": p.tagline,
                              "avatar_url": f"assets/mono_{p.id}.png", "available": True}
                             for p in deps.personas.values()])

    async def new_thread(request: Request) -> JSONResponse:
        return JSONResponse({"thread_id": uuid.uuid4().hex}, status_code=201)

    async def messages(request: Request):
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

    routes = [Route("/personas", personas),
              Route("/threads", new_thread, methods=["POST"]),
              Route("/threads/{thread_id}/messages", messages, methods=["POST"]),
              Route("/threads/{thread_id}/note", note, methods=["POST"])]
    if WEB_DIR.exists():
        routes.append(Mount("/", StaticFiles(directory=WEB_DIR, html=True)))
    return Starlette(routes=routes)
