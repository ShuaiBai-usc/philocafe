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
- PHILOCAFE_SECRET: signs sign-in tokens (7.10). Set it on Vercel; without it, tokens last
  only as long as the server process.
- Accounts, conversation rows and notes (app/store.py) go to the same Postgres; locally they
  stay in memory.
- CRON_SECRET: guards /internal/purge, which the daily Vercel Cron calls. It deletes
  conversations older than PHILOCAFE_RETENTION_HOURS; 0, the default since accounts (7.10),
  keeps everything until the user deletes it.
- PHILOCAFE_ADMIN_TOKEN: guards GET /test/submissions.csv, the export of what testers
  submitted on /test.html (app/submissions.py). Those submissions are not purged.
"""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import re
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from langchain_core.messages import AIMessage, HumanMessage
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.config import ROOT
from app.deps import Deps
from app.graph import CannotRegenerate, build_graph, rewind_last_turn, run_turn
from app.auth import MAX_PASSCODE, MIN_PASSCODE, Tokens, check_passcode, hash_passcode, valid_nickname
from app.prefs import MAX_FEEDBACK, apply_changes, clean_prefs, merge_changes, rule_changes, tag_changes
from app.store import LOCK_FAILURES, MemoryStore, NicknameTaken, PostgresStore
from app.submissions import MAX_TRANSCRIPT, SEVERAL, MemorySubmissions, PostgresSubmissions, to_csv

log = logging.getLogger(__name__)

MAX_TEXT = 2000
MAX_REPLY = 8000                  # a persona reply sent back for a note or a rating
DEFAULT_RETENTION_HOURS = 0       # accounts keep history until the user deletes it (7.10); >0 purges
WEB_DIR = ROOT / "ui" / "web"
CODE_HEADER = "x-philocafe-code"
mimetypes.add_type("application/manifest+json", ".webmanifest")


def last_question(text: str) -> str:
    """The reply's last question (or its first sentence): a note's title when distillation fails."""
    parts = re.findall(r"[^.!?。！？]+[.!?。！？]*", text) or [text]
    asked = [p for p in parts if re.search(r"[?？]", p)]
    return (asked[-1] if asked else parts[0]).strip()[:200]


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


def postgres_pool(url: str):
    """A small pool shared by the checkpointer and the test submissions. Prepared statements
    are off so a transaction-mode pooler (such as Neon's) works. Each connection is checked
    before use: Neon suspends after 5 idle minutes and drops open connections, while the pool
    keeps idle ones for 10, so the first turn after a pause got a dead connection."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    return ConnectionPool(conninfo=url, min_size=0, max_size=4, open=True,
                          check=ConnectionPool.check_connection,
                          kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})


def postgres_checkpointer(pool):
    """LangGraph's Postgres checkpointer on the shared pool."""
    from langgraph.checkpoint.postgres import PostgresSaver

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


def create_app(deps: Deps | None = None, checkpointer=None, access_code: str | None = None,
               submissions=None, store=None, tokens: Tokens | None = None) -> FastAPI:
    deps = deps or deps_from_env()
    url = checkpoint_url()
    pool = postgres_pool(url) if url and (checkpointer is None or submissions is None or store is None) else None
    if checkpointer is None and pool is not None:
        checkpointer = postgres_checkpointer(pool)
    if submissions is None:
        submissions = PostgresSubmissions(pool) if pool is not None else MemorySubmissions()
    if store is None:
        store = PostgresStore(pool) if pool is not None else MemoryStore()
    tokens = tokens or Tokens()
    graph = build_graph(deps, checkpointer=checkpointer)
    code = access_code if access_code is not None else os.environ.get("PHILOCAFE_ACCESS_CODE", "")

    def locked(request: Request) -> JSONResponse | None:
        if code and not hmac.compare_digest(request.headers.get(CODE_HEADER, ""), code):
            return error(401, "access_code", "This café needs an access code.")
        return None

    def signed_in(request: Request) -> tuple[dict | None, JSONResponse | None]:
        """The access code, then the account token (7.10): (user, None) or (None, error)."""
        if denied := locked(request):
            return None, denied
        auth = request.headers.get("authorization", "")
        user_id = tokens.user_id(auth[7:]) if auth.startswith("Bearer ") else None
        user = store.user(user_id) if user_id else None
        if user is None:
            return None, error(401, "sign_in", "Please sign in.")
        return user, None

    def owned(user: dict, thread_id: str) -> dict | None:
        return store.conversation(user["id"], thread_id)

    def thread_state(thread_id: str) -> dict:
        return graph.get_state({"configurable": {"thread_id": thread_id}}).values

    async def json_body(request: Request):
        try:
            body = await request.json() if await request.body() else {}
        except json.JSONDecodeError:
            return None
        return body if isinstance(body, dict) else None

    async def personas(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        return JSONResponse([{"id": p.id, "name": p.name, "era": p.era, "tagline": p.tagline,
                              "avatar_url": f"assets/mono_{p.id}.png", "available": True}
                             for p in deps.personas.values()])

    # ---------- accounts (FR-43) ----------
    async def register(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        nickname, passcode = str(body.get("nickname") or "").strip(), str(body.get("passcode") or "")
        if not valid_nickname(nickname):
            return error(400, "bad_nickname", "Nicknames are 3 to 24 letters, numbers, spaces or . ' - _")
        if not MIN_PASSCODE <= len(passcode) <= MAX_PASSCODE:
            return error(400, "bad_passcode", f"Passcodes are at least {MIN_PASSCODE} characters.")
        try:
            user = await run_in_threadpool(store.create_user, nickname, hash_passcode(passcode))
        except NicknameTaken:
            return error(409, "nickname_taken", "That nickname is taken.")
        return JSONResponse({"token": tokens.issue(user["id"]), "nickname": user["nickname"]}, status_code=201)

    async def login(request: Request) -> JSONResponse:
        if denied := locked(request):
            return denied
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        nickname, passcode = str(body.get("nickname") or "").strip(), str(body.get("passcode") or "")
        if await run_in_threadpool(store.failed_recently, nickname) >= LOCK_FAILURES:
            return error(429, "locked", "Too many tries. Please wait ten minutes.")
        user = await run_in_threadpool(store.user_by_nickname, nickname)
        if user is None or not await run_in_threadpool(check_passcode, passcode[:MAX_PASSCODE], user["passcode_hash"]):
            await run_in_threadpool(store.record_failure, nickname)
            return error(401, "bad_sign_in", "That nickname and passcode don't match.")
        return JSONResponse({"token": tokens.issue(user["id"]), "nickname": user["nickname"]})

    async def me(request: Request) -> JSONResponse:
        user, denied = signed_in(request)
        if denied:
            return denied
        if request.method == "DELETE":                     # FR-45: the account and everything in it
            threads = await run_in_threadpool(store.delete_user, user["id"])
            for t in threads:
                await run_in_threadpool(forget_checkpoint, t)
            return Response(status_code=204)
        if request.method == "PATCH":                      # 7.9: reset (or set) the reply style
            body = await json_body(request)
            if body is None or "prefs" not in body:
                return error(400, "bad_prefs", "Send {prefs}.")
            await run_in_threadpool(store.set_prefs, user["id"], clean_prefs(body["prefs"]))
            user = store.user(user["id"])
        return JSONResponse({"nickname": user["nickname"], "prefs": clean_prefs(user["prefs"]),
                             "paused": bool(user["paused"])})

    def forget_checkpoint(thread_id: str) -> None:
        if hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(thread_id)
        elif graph.checkpointer is not None and hasattr(graph.checkpointer, "delete_thread"):
            graph.checkpointer.delete_thread(thread_id)

    # ---------- conversations (FR-44) ----------
    async def threads(request: Request) -> JSONResponse:
        user, denied = signed_in(request)
        if denied:
            return denied
        if request.method == "GET":
            rows = await run_in_threadpool(store.conversations_of, user["id"])
            return JSONResponse([{"thread_id": c["id"], "persona_id": c["persona_id"], "title": c["title"],
                                  "last_line": c["last_line"], "updated_at": c["updated_at"]} for c in rows])
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        persona_id = str(body.get("persona_id") or deps.config.default_persona)
        if persona_id not in deps.personas:
            return error(404, "unknown_persona", f"No persona {persona_id!r}.")
        c = await run_in_threadpool(store.create_conversation, user["id"], persona_id)
        return JSONResponse({"thread_id": c["id"], "persona_id": persona_id}, status_code=201)

    async def thread(request: Request):
        user, denied = signed_in(request)
        if denied:
            return denied
        thread_id = request.path_params["thread_id"]
        c = await run_in_threadpool(owned, user, thread_id)
        if c is None:
            return error(404, "unknown_thread", "No such conversation.")
        if request.method == "DELETE":
            await run_in_threadpool(store.delete_conversation, user["id"], thread_id)
            await run_in_threadpool(forget_checkpoint, thread_id)
            return Response(status_code=204)
        state = await run_in_threadpool(thread_state, thread_id)
        out = []
        for m in state.get("messages") or []:
            if isinstance(m, HumanMessage):
                out.append({"id": m.id, "role": "user", "text": m.content})
            elif isinstance(m, AIMessage):
                system = m.name == "system"
                out.append({"id": m.id, "role": "system" if system else "persona", "text": m.content,
                            "citations": [] if system else m.additional_kwargs.get("citations", []),
                            "rating": None if system else c["ratings"].get(m.id)})
        return JSONResponse({"thread_id": thread_id, "persona_id": c["persona_id"], "title": c["title"],
                             "messages": out, "paused": bool(user["paused"])})

    def run_and_record(user: dict, thread_id: str, events, first_line: str):
        """Stream the turn, then keep the conversation row and the user's pause up to date (7.10)."""
        yield from events
        state = thread_state(thread_id)
        messages = state.get("messages") or []
        last = messages[-1].content if messages else ""
        store.touch(thread_id, first_line, last)
        store.set_paused(user["id"], state.get("mode") == "support")

    async def messages(request: Request):
        user, denied = signed_in(request)
        if denied:
            return denied
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        thread_id = request.path_params["thread_id"]
        c = await run_in_threadpool(owned, user, thread_id)
        if c is None:
            return error(404, "unknown_thread", "No such conversation.")
        prefs = clean_prefs(user["prefs"])                 # 7.9: the account's preferences, clamped
        first = next((m.content for m in (thread_state(thread_id).get("messages") or [])
                      if isinstance(m, HumanMessage)), "")
        if body.get("regenerate") is True:               # FR-41: answer the latest message again
            try:
                text, persona_id = await run_in_threadpool(rewind_last_turn, graph, thread_id)
            except CannotRegenerate as e:
                return error(409, "cannot_regenerate", str(e))
            events = run_turn(graph, thread_id, text, persona_id, None, prefs, bool(user["paused"]))
            return StreamingResponse((sse(e) for e in run_and_record(user, thread_id, events, first or text)),
                                     media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        text = str(body.get("text") or "").strip()
        if not text:
            return error(400, "empty_text", "The message is empty.")
        if len(text) > MAX_TEXT:
            return error(400, "text_too_long", f"Messages are limited to {MAX_TEXT} characters.")
        intent = body.get("intent")
        if intent not in (None, "return"):
            return error(400, "bad_intent", "intent must be \"return\" or absent.")
        # One conversation is one philosopher (7.10); the pause belongs to the user (FR-32).
        events = run_turn(graph, thread_id, text, c["persona_id"], intent, prefs, bool(user["paused"]))
        return StreamingResponse((sse(e) for e in run_and_record(user, thread_id, events, first or text)),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    def exchange(state: dict, message_id: str) -> tuple[str, AIMessage] | None:
        """The persona reply with this id and the user message before it."""
        msgs = state.get("messages") or []
        i = next((k for k, m in enumerate(msgs) if isinstance(m, AIMessage) and m.id == message_id
                  and m.name != "system"), None)
        if i is None:
            return None
        you = next((m.content for m in reversed(msgs[:i]) if isinstance(m, HumanMessage)), "")
        return you, msgs[i]

    # ---------- notes (FR-07, 7.7) ----------
    async def note(request: Request) -> JSONResponse:
        user, denied = signed_in(request)
        if denied:
            return denied
        thread_id = request.path_params["thread_id"]
        c = await run_in_threadpool(owned, user, thread_id)
        if c is None:
            return error(404, "unknown_thread", "No such conversation.")
        if user["paused"]:
            return error(409, "support_mode", "Notes are not made from a paused conversation.")
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        state = await run_in_threadpool(thread_state, thread_id)
        found = exchange(state, str(body.get("message_id") or ""))
        if found is None:
            return error(404, "unknown_message", "No such reply in this conversation.")
        you, reply = found
        persona = deps.personas.get(c["persona_id"])
        name = persona.name if persona else "the philosopher"
        distilled = None
        if deps.distill_note is not None:
            msgs = ([HumanMessage(you)] if you else []) + [reply]
            try:
                distilled = await run_in_threadpool(deps.distill_note, name, msgs)
            except Exception as e:
                log.warning("note distillation failed: %s", type(e).__name__)
        if not distilled:                                   # 7.7: the reply's own question stands in
            distilled = {"title": last_question(reply.content), "why": f"From your talk about “{you}”." if you
                         else "A thought to revisit later.", "topic": "From your conversation"}
        cites = [{"n": str(k + 1), "where": f"{x['work']}, {x['section']}" if x.get("section") else x.get("work", ""),
                  "quote": x.get("quote", ""), "passage": x.get("passage", ""), "url": x.get("source_url", "")}
                 for k, x in enumerate(reply.additional_kwargs.get("citations", []))]
        saved = await run_in_threadpool(store.add_note, user["id"], {
            "persona_id": c["persona_id"], "thread_id": thread_id, "message_id": reply.id, **distilled, "reflection": "",
            "from": {"you": you, "them": reply.content, "cites": cites}})
        return JSONResponse(saved, status_code=201)

    async def notes(request: Request):
        user, denied = signed_in(request)
        if denied:
            return denied
        if request.method == "GET":
            return JSONResponse(await run_in_threadpool(store.notes_of, user["id"]))
        body = await json_body(request)                    # POST: import a note a device kept before accounts
        if not body or not isinstance(body.get("note"), dict):
            return error(400, "bad_note", "Send {note}.")
        return JSONResponse(await run_in_threadpool(store.add_note, user["id"], body["note"]), status_code=201)

    async def one_note(request: Request):
        user, denied = signed_in(request)
        if denied:
            return denied
        note_id = request.path_params["note_id"]
        if request.method == "DELETE":
            ok = await run_in_threadpool(store.delete_note, user["id"], note_id)
            return Response(status_code=204) if ok else error(404, "unknown_note", "No such note.")
        body = await json_body(request)
        if body is None or not isinstance(body.get("reflection"), str):
            return error(400, "bad_note", "Send {reflection}.")
        saved = await run_in_threadpool(store.update_note, user["id"], note_id, body["reflection"])
        return JSONResponse(saved) if saved else error(404, "unknown_note", "No such note.")

    # ---------- ratings and reply preferences (7.9) ----------
    async def preferences(request: Request) -> JSONResponse:
        """One thumb (or its feedback window) on a stored reply -> the user's updated preferences."""
        user, denied = signed_in(request)
        if denied:
            return denied
        body = await json_body(request)
        if body is None:
            return error(400, "bad_json", "The request body is not JSON.")
        rating = body.get("rating")
        if rating not in ("up", "down", "none"):
            return error(400, "bad_rating", "rating must be \"up\", \"down\" or \"none\".")
        thread_id = str(body.get("thread_id") or "")
        c = await run_in_threadpool(owned, user, thread_id)
        if c is None:
            return error(404, "unknown_thread", "No such conversation.")
        found = exchange(await run_in_threadpool(thread_state, thread_id), str(body.get("message_id") or ""))
        if found is None:
            return error(404, "unknown_message", "No such reply in this conversation.")
        user_text, reply_msg = found
        reply = reply_msg.content[:MAX_REPLY]
        await run_in_threadpool(store.set_rating, thread_id, reply_msg.id, None if rating == "none" else rating)
        prefs = clean_prefs(user["prefs"])
        if rating == "none":
            return JSONResponse({"prefs": prefs, "source": "none"})
        persona = deps.personas.get(c["persona_id"])
        # The feedback window (long-press on a filled thumb): tags are fixed steps; the note goes to the
        # model as data and only moves dials. Neither reaches the persona prompt (FR-37).
        feedback = body.get("feedback") if isinstance(body.get("feedback"), dict) else None
        tags = tag_changes(rating, feedback.get("tags")) if feedback else {}
        text = str(feedback.get("text") or "").strip()[:MAX_FEEDBACK] if feedback else ""
        changes, source = None, "rule"
        if deps.tune_prefs is not None and (feedback is None or text):
            try:
                changes = await run_in_threadpool(deps.tune_prefs, rating, persona.name if persona else "",
                                                  user_text[:MAX_TEXT], reply, prefs, text)
                source = "model"
            except Exception as e:
                log.warning("preference update failed, using the offline rule: %s", type(e).__name__)
        if changes is None:
            changes = {} if feedback is not None else rule_changes(rating, reply)
            source = "tags" if feedback is not None else source
        new = apply_changes(prefs, merge_changes(tags, changes))
        await run_in_threadpool(store.set_prefs, user["id"], new)
        return JSONResponse({"prefs": new, "source": source})

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
        await run_in_threadpool(store.forget_threads, threads)
        log.info("purged %d conversations older than %s hours", len(threads), hours)
        return JSONResponse({"deleted": len(threads)})

    async def submit_test(request: Request) -> JSONResponse:
        # Open without the access code: testers may have chatted in the home-screen app, whose
        # storage (and saved code) is separate from Safari's on iPhone. Size limits keep it cheap.
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return error(400, "bad_json", "The request body is not JSON.")
        if not isinstance(body, dict):
            return error(400, "bad_json", "The request body must be a JSON object.")
        picked = body.get("personas")
        if picked is None and body.get("persona") == SEVERAL:
            picked = [SEVERAL]                  # a test page cached from before multi-select
        elif picked is None:
            picked = [body.get("persona")]
        known = set(deps.personas) | {SEVERAL}
        if not isinstance(picked, list) or not picked or any(p not in known for p in picked) \
                or (SEVERAL in picked and len(picked) > 1):
            return error(400, "bad_persona", "Pick who you talked with.")
        persona = ",".join(dict.fromkeys(picked))     # e.g. "socrates,seneca" (page order), duplicates dropped
        transcript = str(body.get("transcript") or "").strip()
        if not transcript:
            return error(400, "empty_transcript", "Paste your conversation first.")
        if len(transcript) > MAX_TRANSCRIPT:
            return error(400, "transcript_too_long",
                         f"Conversations are limited to {MAX_TRANSCRIPT} characters. Please trim it a little.")
        try:
            sid = await run_in_threadpool(submissions.add, persona, transcript)
        except Exception as e:
            log.exception("test submission failed")
            return error(502, "save_failed", type(e).__name__)
        return JSONResponse({"id": sid}, status_code=201)

    async def export_tests(request: Request):
        token = os.environ.get("PHILOCAFE_ADMIN_TOKEN", "")
        if not token or not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
            return error(401, "admin_only", "This export needs the admin token.")
        rows = await run_in_threadpool(submissions.all)
        return Response(to_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="philocafe-test-submissions.csv"',
                                 "Cache-Control": "no-store"})

    routes = [Route("/personas", personas),
              Route("/auth/register", register, methods=["POST"]),
              Route("/auth/login", login, methods=["POST"]),
              Route("/me", me, methods=["GET", "PATCH", "DELETE"]),
              Route("/threads", threads, methods=["GET", "POST"]),
              Route("/threads/{thread_id}", thread, methods=["GET", "DELETE"]),
              Route("/threads/{thread_id}/messages", messages, methods=["POST"]),
              Route("/threads/{thread_id}/note", note, methods=["POST"]),
              Route("/notes", notes, methods=["GET", "POST"]),
              Route("/notes/{note_id}", one_note, methods=["PATCH", "DELETE"]),
              Route("/preferences", preferences, methods=["POST"]),
              Route("/internal/purge", purge),
              Route("/test/submissions", submit_test, methods=["POST"]),
              Route("/test/submissions.csv", export_tests)]
    # The same mount on Vercel: it promotes StaticFiles mounts to its CDN at build time, and the
    # function serves the files itself if it does not. Declared last, so the API routes win.
    if WEB_DIR.exists():
        routes.append(Mount("/", StaticFiles(directory=WEB_DIR, html=True)))
    return FastAPI(routes=routes, docs_url=None, redoc_url=None, openapi_url=None)
