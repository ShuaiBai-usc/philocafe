"""Persona node (M-03): retrieves passages, streams the persona's reply and
checks every quote before it reaches the user (FR-11, FR-12).

The system prompt (persona voice + quoting rules) is the same on every turn so
it can be cached; this turn's passages go in a system message after the
user's latest message.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage

from app.deps import Deps
from app.events import emit
from app.personas import PersonaConfig
from app.quotes import LeadingNotesFilter, QuoteFilter
from app.retrieval import Chunk
from app.state import TurnState
from app.translate import needs_translation

log = logging.getLogger(__name__)

QUOTING_RULES = """Quoting the dialogues:
- A turn may come with passages from Plato's dialogues, each with an id. Quote only from those passages, word for word, and keep each quote to a sentence or two.
- Wrap every quote in a tag with its passage id: <q id="PASSAGE_ID">exact words</q>. Use the tag only for quotes, and don't put quotation marks around anything else.
- Each passage line starts with its speaker ("Meno:", "Socrates:"). Leave the label out of the quote, and if the words are someone else's, say who said them.
- Lines starting with [speaker uncertain] may not be your words; don't quote them as your own.
- If you reply in a language other than English, still quote only from the passages: put the exact English words in src and your translation between the tags, like <q id="PASSAGE_ID" src="exact English words">your translation</q>. Don't use double quotation marks inside src.
- If no passage fits what you want to say, don't quote; just talk."""

REPLY_RULE = ("Write only what you say to the person. Never include notes to yourself, drafts, reasoning, "
              "or any tags other than <q>.")

REENTRY_NOTE = ("The person stepped away from your conversation for a while to get support, and has now asked "
                "to continue with you. Welcome them back warmly in a sentence, don't bring up the difficult "
                "topic unless they do, and follow their lead.")

SHORT_QUERY_WORDS = 6


def system_prompt(persona: PersonaConfig) -> str:
    style = "\n".join(f"- {rule}" for rule in persona.style)
    return f"{persona.prompt}\n\nHow you talk:\n{style}\n- {REPLY_RULE}\n\n{QUOTING_RULES}"


def passages_note(chunks: Sequence[Chunk], retrieved: bool) -> str:
    if not retrieved:
        return "No passages come with this turn. Don't quote."
    if not chunks:
        # UC-01 extension: nothing relevant in the corpus.
        return ("No passage in the dialogues matched this turn. Don't quote; if you draw on the dialogues, "
                "say you are speaking from memory rather than from the texts.")
    blocks = []
    for c in chunks:
        source = f"{c['work']}, {c['section']}" if c["section"] else c["work"]
        blocks.append(f'<passage id="{c["chunk_id"]}" source="{source}">\n{c["text"]}\n</passage>')
    return "Passages for this turn (quote only from these):\n\n" + "\n\n".join(blocks)


def retrieval_query(messages: Sequence[AnyMessage]) -> str:
    """The latest user message, with the one before it when it is short ("why?")."""
    said = [m.content for m in messages if isinstance(m, HumanMessage)]
    query = said[-1]
    if len(query.split()) < SHORT_QUERY_WORDS and len(said) > 1:
        query = f"{said[-2]} {query}"
    return query


def persona_node(state: TurnState, deps: Deps) -> dict:
    persona = deps.personas[state["persona_id"]]
    emit("voice", speaker="persona", persona_id=persona.id)

    wants_passages = state["safety"]["needs_retrieval"]
    chunks: list[Chunk] = []
    query = ""
    if wants_passages:
        query = retrieval_query(state["messages"])
        if deps.translate is not None and needs_translation(query):
            try:
                query = deps.translate(query)
            except Exception as e:   # search with the original words rather than fail the turn
                log.warning("query translation failed: %s", type(e).__name__)
        chunks = deps.retrieve(persona.corpus, query,
                               k=persona.k or deps.config.k,
                               min_score=persona.min_score if persona.min_score is not None else deps.config.min_score)

    notes, quotes = LeadingNotesFilter(), QuoteFilter(chunks)
    parts: list[str] = []

    def send(outputs):
        for kind, value in outputs:
            if kind == "text":
                emit("token", text=value)
                parts.append(value)
            else:
                # quote and passage are optional 7.2 fields: the checked words and the full passage.
                emit("citation", chunk_id=value["chunk_id"], work=value["work"], section=value["section"],
                     source_url=value["source_url"], quote=value["quote"], passage=value["text"])

    returning = state.get("mode") == "support"      # FR-32: safety let the persona back in
    notes_for_turn = ([SystemMessage(REENTRY_NOTE)] if returning else []) + [SystemMessage(passages_note(chunks, wants_passages))]
    messages = [*state["messages"], *notes_for_turn]
    for delta in deps.generate(system_prompt(persona), messages):
        send(quotes.feed(notes.feed(delta)))
    send(quotes.feed(notes.close()))
    send(quotes.close())
    if notes.dropped:
        log.warning("dropped notes the voice model wrote before its reply")

    reply = "".join(parts)
    return {"retrieved": chunks, "reply": reply, "citations": quotes.cited, "quotes": quotes.checks,
            "retrieval_query": query, "mode": "persona", "messages": [AIMessage(reply, name=persona.id)]}
