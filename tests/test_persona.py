"""Persona node: retrieval, passages note, quote check through the graph."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.fakes import FAKE_CHUNKS, FakeSafetyModel, FakeVoice, fake_deps
from app.graph import build_graph, run_turn
from app.config import ROOT
from app.persona import passages_note, quoting_rules, retrieval_query, system_prompt
from app.personas import load_persona, load_personas

CHUNK = FAKE_CHUNKS[0]
GOOD = ["Well, ", f'<q id="{CHUNK["chunk_id"]}">can either a young man', ' or an elder one be good</q>', "? Tell me."]
BAD = ["As I said, ", f'<q id="{CHUNK["chunk_id"]}">know thyself and all will be well</q>', "."]


class RecordingRetrieve:
    def __init__(self, chunks=FAKE_CHUNKS):
        self.chunks = list(chunks)
        self.calls = []

    def __call__(self, persona, query, k=5, min_score=None):
        self.calls.append({"persona": persona, "query": query, "k": k, "min_score": min_score})
        return self.chunks[:k]


def turn(deps, text="is virtue teachable", thread="t1"):
    graph = build_graph(deps)
    events = list(run_turn(graph, thread, text, "socrates"))
    return events, graph.get_state({"configurable": {"thread_id": thread}}).values


def of(events, type_):
    return [e["data"] for e in events if e["type"] == type_]


def test_verified_quote_streams_with_citation():
    voice = FakeVoice(GOOD)
    events, state = turn(fake_deps(generate=voice))
    assert "".join(t["text"] for t in of(events, "token")) == (
        "Well, “can either a young man or an elder one be good”? Tell me.")
    assert of(events, "citation") == [{"chunk_id": CHUNK["chunk_id"], "work": "Meno", "section": "",
                                       "source_url": CHUNK["source_url"],
                                       "quote": "can either a young man or an elder one be good",
                                       "passage": CHUNK["text"]}]
    assert state["citations"] == [CHUNK["chunk_id"]]
    assert of(events, "trace")[0]["skipped"] == []
    assert state["messages"][-1].content == state["reply"]


def test_invented_quote_is_paraphrased_and_traced():
    events, state = turn(fake_deps(generate=FakeVoice(BAD)))
    assert of(events, "citation") == []
    assert state["reply"] == "As I said, know thyself and all will be well."
    assert of(events, "trace")[0]["skipped"] == [{"chunk_id": CHUNK["chunk_id"], "reason": "not_in_passages"}]


def test_passages_go_in_a_system_message_after_the_user_turn():
    voice, retrieve = FakeVoice(), RecordingRetrieve()
    turn(fake_deps(generate=voice, retrieve=retrieve))
    assert retrieve.calls == [{"persona": "socrates", "query": "is virtue teachable", "k": 5, "min_score": None}]
    *history, note = voice.last_messages
    assert isinstance(history[-1], HumanMessage) and isinstance(note, SystemMessage)
    assert f'<passage id="{CHUNK["chunk_id"]}" source="Meno">' in note.content
    assert voice.last_system.startswith("You are Socrates of Athens")
    assert quoting_rules(load_personas()["socrates"]) in voice.last_system
    assert "passages from Plato's dialogues" in voice.last_system


def test_no_retrieval_when_safety_says_so():
    voice, retrieve = FakeVoice(), RecordingRetrieve()
    models = [FakeSafetyModel("jev", needs_retrieval=False)]
    events, _ = turn(fake_deps(generate=voice, retrieve=retrieve, safety_models=models), text="hello there")
    assert retrieve.calls == []
    assert voice.last_messages[-1].content == "No passages come with this turn. Don't quote."
    assert of(events, "trace")[0]["retrieved"] == []


def test_no_matching_passage_tells_persona_to_speak_freely():
    voice = FakeVoice()
    turn(fake_deps(generate=voice, retrieve=RecordingRetrieve(chunks=[])))
    assert "speaking from memory" in voice.last_messages[-1].content


def test_retrieval_query_adds_previous_message_when_short():
    messages = [HumanMessage("is courage a kind of knowledge"), AIMessage("What do you think?"), HumanMessage("why?")]
    assert retrieval_query(messages) == "is courage a kind of knowledge why?"
    assert retrieval_query(messages[:1]) == "is courage a kind of knowledge"


def test_passages_note_shows_section_when_present():
    chunk = dict(CHUNK, section="Book II")
    assert 'source="Meno, Book II"' in passages_note([chunk], retrieved=True)


def test_socrates_config_loads():
    socrates = load_personas()["socrates"]
    assert socrates.corpus == "socrates" and socrates.k == 5 and socrates.style
    assert "How you talk:" in system_prompt(socrates)


@pytest.mark.parametrize("persona_id", ["seneca", "epictetus", "montaigne", "schopenhauer"])
def test_new_persona_configs_name_their_own_texts(persona_id):
    persona = load_personas()[persona_id]
    prompt = system_prompt(persona)
    assert persona.corpus == persona_id and persona.style and persona.tier2_passages == {}
    assert prompt.startswith(f"You are ") and persona.name in prompt.split("\n")[0]
    assert f"passages from {persona.texts}" in prompt
    assert "Plato" not in prompt and "{texts}" not in prompt
    assert any("ending one's life" in rule for rule in persona.style)


def test_every_persona_corpus_has_processed_passages():
    for persona in load_personas().values():
        assert (ROOT / "data" / "processed" / persona.corpus / "rag_passages.jsonl").exists(), persona.id


def test_no_match_note_names_the_persona_texts():
    note = passages_note([], retrieved=True, texts="your letters and essays")
    assert note.startswith("No passage in your letters and essays matched this turn.")


def test_bad_tier2_mark_is_rejected(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text("id: x\nname: X\nprompt: hi\ntier2_passages:\n  x-1: dangerous\n")
    with pytest.raises(ValueError):
        load_persona(path)


class RecordingTranslate:
    def __init__(self, result="is virtue teachable", fail=False):
        self.result, self.fail, self.calls = result, fail, []

    def __call__(self, text):
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("translation down")
        return self.result


def test_chinese_question_is_translated_before_retrieval():
    retrieve, translate = RecordingRetrieve(), RecordingTranslate()
    events, state = turn(fake_deps(retrieve=retrieve, translate=translate), text="美德可以教吗？")
    assert translate.calls == ["美德可以教吗？"]
    assert retrieve.calls[0]["query"] == "is virtue teachable"
    assert state["retrieval_query"] == "is virtue teachable"
    assert state["messages"][-2].content == "美德可以教吗？"     # the persona still sees the user's words


def test_english_question_is_not_translated():
    translate = RecordingTranslate()
    _, state = turn(fake_deps(translate=translate))
    assert translate.calls == [] and state["retrieval_query"] == "is virtue teachable"


def test_failed_translation_searches_the_original_words():
    retrieve = RecordingRetrieve()
    events, state = turn(fake_deps(retrieve=retrieve, translate=RecordingTranslate(fail=True)), text="美德可以教吗？")
    assert retrieve.calls[0]["query"] == "美德可以教吗？"
    assert events[-1]["type"] == "done"


@pytest.mark.parametrize("text, expected", [("美德可以教吗？", True), ("is virtue teachable?", False),
                                            ("Добродетель можно научить?", True), ("¿Se puede enseñar?", False),
                                            ("42?", False)])
def test_needs_translation(text, expected):
    from app.translate import needs_translation
    assert needs_translation(text) is expected


def test_quoting_rules_explain_translated_quotes():
    assert 'src="exact English words"' in quoting_rules(load_personas()["seneca"])


def test_leaked_notes_are_not_shown():
    voice = FakeVoice(["<reasoning>plan the reply", "</reasoning>", "Tell me more."])
    events, state = turn(fake_deps(generate=voice))
    assert state["reply"] == "Tell me more."
    assert "reasoning" not in "".join(e["data"].get("text", "") for e in events if e["type"] == "token")
