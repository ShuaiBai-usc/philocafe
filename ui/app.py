"""PhiloCafe midterm UI (M-08): chat, debug panel and source cards.

    .venv/bin/streamlit run ui/app.py              # real services (.env keys, built database)
    .venv/bin/streamlit run ui/app.py -- --fake    # offline stand-ins, no keys or network

It calls the graph in-process and consumes the same 7.2 events the final UI
will get over HTTP. No key or environment value is ever shown.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import build_graph, run_turn  # noqa: E402

FAKE = "--fake" in sys.argv
TIER_NAMES = {0: "Everyday", 1: "Mild distress", 2: "Elevated", 3: "High risk"}
AVATARS = {"user": "🙂", "persona": "🏛️", "system": "🛟"}


@st.cache_resource(show_spinner="Opening the café…")
def runtime(fake: bool):
    if fake:
        from app.fakes import FAKE_QUOTING_REPLY, FakeVoice, fake_deps
        deps = fake_deps(generate=FakeVoice([w + " " for w in FAKE_QUOTING_REPLY.split(" ")], delay=0.04))
    else:
        from app import retrieval
        from app.deps import default_deps
        deps = default_deps()
        retrieval.retrieve("socrates", "warm up", k=1)   # loads the embedding model before the first turn
    return build_graph(deps), deps


def md(text: str) -> str:
    return text.replace("$", r"\$")     # keep Streamlit from reading $…$ as LaTeX


def new_conversation() -> None:
    st.session_state.thread_id = uuid.uuid4().hex
    st.session_state.messages = []
    st.session_state.debug = None


def speaker_label(msg: dict, personas) -> str:
    if msg["role"] == "system":
        return "**PhiloCafe support** · the philosopher has stepped aside"
    return f"**{personas[msg['persona_id']].name}**"


def render_extras(msg: dict) -> None:
    if msg.get("resources"):
        st.markdown("\n".join(f"- **{r['name']}**: {r['contact']}" for r in msg["resources"]))
    for n, c in enumerate(msg.get("citations", []), start=1):
        where = f"{c['work']}, {c['section']}" if c.get("section") else c["work"]
        with st.container(border=True):
            st.markdown(f"📜 **[{n}] {where}** · Plato, tr. Jowett")
            for quote in c.get("quoted", []):
                st.markdown(f"> {md(quote)}")      # the English original that was checked
            with st.expander("Full passage"):
                st.markdown(md(c.get("text", "")).replace("\n", "  \n"))
            st.caption(f"[Read it in the source]({c['source_url']}) · `{c['chunk_id']}`")


def render_message(msg: dict, personas) -> None:
    with st.chat_message(msg["role"], avatar=AVATARS[msg["role"]]):
        if msg["role"] != "user":
            st.markdown(speaker_label(msg, personas))
        st.markdown(md(msg["text"]))
        render_extras(msg)


def run(graph, deps, text: str, persona_id: str) -> None:
    thread_id = st.session_state.thread_id
    user_msg = {"role": "user", "text": text}
    st.session_state.messages.append(user_msg)
    render_message(user_msg, deps.personas)

    reply = {"role": None, "persona_id": persona_id, "text": "", "citations": [], "resources": None}
    debug = {"safety": None, "trace": None, "error": None, "ttft_ms": None}
    container = placeholder = None
    start = time.perf_counter()
    for ev in run_turn(graph, thread_id, text, persona_id):
        kind, data = ev["type"], ev["data"]
        if kind == "voice":
            reply["role"] = "persona" if data["speaker"] == "persona" else "system"
            container = st.chat_message(reply["role"], avatar=AVATARS[reply["role"]])
            container.markdown(speaker_label(reply, deps.personas))
            placeholder = container.empty()
        elif kind == "token":
            if debug["ttft_ms"] is None:
                debug["ttft_ms"] = round((time.perf_counter() - start) * 1000)
            reply["text"] += data["text"]
            placeholder.markdown(md(reply["text"]) + "▌")
        elif kind == "citation":
            # The event follows its verified quote, so the marker lands right after it (display only).
            reply["citations"].append(dict(data))
            reply["text"] += f" [{len(reply['citations'])}]"
            placeholder.markdown(md(reply["text"]) + "▌")
        elif kind == "exit":
            reply["resources"] = data["resources"]
        elif kind in ("safety", "trace", "error"):
            debug[kind] = data

    state = graph.get_state({"configurable": {"thread_id": thread_id}}).values
    debug["retrieved"] = state.get("retrieved", [])
    debug["mode"] = state.get("mode", "persona")
    records = deps.decision_log.for_thread(thread_id)
    debug["safety_errors"] = list(records[-1].errors) if records else []
    debug["user_text"], debug["retrieval_query"] = text, state.get("retrieval_query", "")
    passages = {c["chunk_id"]: c for c in debug["retrieved"]}
    for c in reply["citations"]:      # quote and passage arrive on the citation event
        c["text"] = c.get("passage") or passages.get(c["chunk_id"], {}).get("text", "")
        c["quoted"] = [c["quote"]] if c.get("quote") else []
    st.session_state.debug = debug

    if container is not None:
        placeholder.markdown(md(reply["text"]))
        with container:
            render_extras(reply)
        st.session_state.messages.append(reply)
    if debug["error"]:
        st.error(f"Something went wrong ({debug['error']['code']}). Please try again.")


def render_debug(debug: dict | None) -> None:
    st.sidebar.divider()
    st.sidebar.subheader("Debug")
    if not debug:
        st.sidebar.caption("Send a message to see how the turn was handled.")
        return
    s = debug["safety"]
    if s:
        tier_line = f"**Tier {s['tier']}** · {TIER_NAMES[s['tier']]}"
        if s["tier"] == 2:
            tier_line += " (flagged; at the midterm the persona continues)"
        st.sidebar.markdown(tier_line)
        st.sidebar.markdown(f"Probability **{s['probability']:.2f}** against threshold {s['threshold']:.2f}")
        st.sidebar.markdown(f"Source **{s['source']}** · `{s['model_version']}`")
        for err in debug["safety_errors"]:
            st.sidebar.caption(f"failed first: {err}")
    route = "exit flow" if debug["mode"] == "support" else "socrates (fixed at the midterm)"
    st.sidebar.markdown(f"Route: {route}")
    query = debug.get("retrieval_query")
    if query and query != debug.get("user_text"):
        st.sidebar.markdown(f"Searched for (translated): “{md(query)}”")

    if debug["retrieved"]:
        st.sidebar.markdown("Retrieved passages\n" + "\n".join(
            f"- `{c['chunk_id']}` · {c['score']:.2f}" for c in debug["retrieved"]))
    else:
        st.sidebar.markdown("Retrieved passages: none")
    trace = debug["trace"] or {}
    for item in trace.get("skipped", []):
        st.sidebar.caption(f"skipped `{item['chunk_id']}`: {item['reason']}")
    timings = " · ".join(f"{n['name']} {n['ms']:.0f} ms" for n in trace.get("nodes", []))
    if timings:
        st.sidebar.markdown(f"Nodes: {timings}")
    if debug["ttft_ms"] is not None:
        st.sidebar.markdown(f"First token after {debug['ttft_ms']} ms")


def main() -> None:
    st.set_page_config(page_title="PhiloCafe", page_icon="☕", layout="centered")
    graph, deps = runtime(FAKE)
    if "thread_id" not in st.session_state:
        new_conversation()

    personas = deps.personas
    with st.sidebar:
        st.title("☕ PhiloCafe")
        persona_id = st.selectbox("Philosopher", list(personas), format_func=lambda p: personas[p].name)
        p = personas[persona_id]
        st.caption(f"{p.era} · {p.tagline}")
        st.button("New conversation", on_click=new_conversation, width="stretch")
        if FAKE:
            st.warning("Offline demo: safety, retrieval and voice are stand-ins.")

    st.markdown(f"#### Talk with {p.name}")
    for msg in st.session_state.messages:
        render_message(msg, personas)

    text = st.chat_input(f"Bring {p.name} a question, a worry or an idea")
    if text:
        run(graph, deps, text, persona_id)

    debug = st.session_state.debug
    if debug and debug.get("mode") == "support":
        st.caption(f"{p.name} has stepped aside for this conversation. "
                   "Start a new conversation to talk with him again.")
    render_debug(debug)


main()
