"""Streaming quote check (FR-12)."""

import pytest

from app.quotes import LeadingNotesFilter, QuoteFilter
from app.retrieval import Chunk

MENO = Chunk(chunk_id="socrates-meno-aaaa1111", persona="socrates", work="Meno", section="",
             text="Meno: Can you tell me, Socrates, whether virtue is acquired by teaching or by practice?\n"
                  "Socrates: You must think me very fortunate to know how virtue is acquired.",
             source_url="https://example.invalid/meno", score=0.7)
APOLOGY = Chunk(chunk_id="socrates-apology-bbbb2222", persona="socrates", work="Apology", section="",
                text="Socrates: And the truth of this I will endeavour to prove to you.\n"
                     "[speaker uncertain] Come hither, Meletus, and let me ask a question of you.",
                source_url="https://example.invalid/apology", score=0.5)


def run(reply, chunks=(MENO, APOLOGY), step=None):
    """Feed the reply whole, or `step` characters at a time; return (text, cited ids, checks)."""
    qf = QuoteFilter(list(chunks))
    pieces = [reply] if step is None else [reply[i:i + step] for i in range(0, len(reply), step)]
    out = [o for piece in pieces for o in qf.feed(piece)] + qf.close()
    text = "".join(v for kind, v in out if kind == "text")
    cited = [v["chunk_id"] for kind, v in out if kind == "citation"]
    return text, cited, qf.checks


@pytest.mark.parametrize("step", [None, 1, 3, 7])
def test_verified_quote_is_shown_and_cited_however_it_streams(step):
    reply = 'As I told Meno, <q id="socrates-meno-aaaa1111">You must think me very fortunate</q>. What do you think?'
    text, cited, checks = run(reply, step=step)
    assert text == "As I told Meno, “You must think me very fortunate”. What do you think?"
    assert cited == ["socrates-meno-aaaa1111"]
    assert [(c["ok"], c["reason"]) for c in checks] == [(True, "verified")]


def test_plain_text_passes_through_unchanged():
    reply = "Is 3 < 5 always? Tell me <b>why</b> you think so."
    for step in (None, 1, 2):
        assert run(reply, step=step)[0] == reply


def test_wrong_id_is_reattributed():
    text, cited, _ = run('<q id="socrates-apology-bbbb2222">know how virtue is acquired</q>')
    assert cited == ["socrates-meno-aaaa1111"]
    assert text == "“know how virtue is acquired”"


def test_quote_not_in_passages_becomes_paraphrase():
    text, cited, checks = run('<q id="socrates-meno-aaaa1111">The unexamined life is not worth living</q>')
    assert text == "The unexamined life is not worth living"
    assert cited == []
    assert checks[0] == {"chunk_id": "socrates-meno-aaaa1111", "text": "The unexamined life is not worth living",
                         "translation": None, "ok": False, "reason": "not_in_passages"}


def test_speaker_uncertain_line_is_not_quoted():
    text, cited, checks = run('<q id="socrates-apology-bbbb2222">let me ask a question of you</q>')
    assert (text, cited) == ("let me ask a question of you", [])
    assert checks[0]["reason"] == "speaker_uncertain"


def test_unclosed_quote_becomes_paraphrase():
    text, cited, checks = run('He said <q id="socrates-meno-aaaa1111">You must think me very fortunate')
    assert text == "He said You must think me very fortunate"
    assert cited == [] and checks[0]["reason"] == "unclosed"


def test_too_short_quote_is_not_cited():
    _, cited, checks = run('<q id="socrates-meno-aaaa1111">virtue</q>')
    assert cited == [] and checks[0]["reason"] == "too_short"


def test_tag_without_id_and_stray_close_tag():
    text, cited, _ = run('<q>whether virtue is acquired by teaching</q> and then </q>more')
    assert text == "“whether virtue is acquired by teaching” and then more"
    assert cited == ["socrates-meno-aaaa1111"]


def test_quote_with_ellipsis_and_typographic_marks():
    text, cited, _ = run('<q id="socrates-meno-aaaa1111">“Can you tell me, Socrates … by teaching or by practice?”</q>')
    assert cited == ["socrates-meno-aaaa1111"]
    assert text == "“Can you tell me, Socrates … by teaching or by practice?”"


def test_same_chunk_cited_once():
    reply = ('<q id="socrates-meno-aaaa1111">You must think me very fortunate</q> and '
             '<q id="socrates-meno-aaaa1111">how virtue is acquired</q>')
    assert run(reply)[1] == ["socrates-meno-aaaa1111"]


def test_untagged_quotes_are_measured_not_changed():
    reply = 'You once said "And the truth of this I will endeavour to prove" and "nothing is ever really certain at all".'
    text, cited, checks = run(reply)
    assert text == reply and cited == []
    assert [(c["chunk_id"], c["reason"]) for c in checks] == [
        ("socrates-apology-bbbb2222", "untagged_found"), (None, "untagged_not_found")]


@pytest.mark.parametrize("step", [None, 1, 5])
def test_translated_quote_is_checked_on_src_and_shows_translation(step):
    reply = ('我曾对美诺说：<q id="socrates-meno-aaaa1111" src="You must think me very fortunate">'
             '你一定觉得我很幸运</q>。你怎么看？')
    text, cited, checks = run(reply, step=step)
    assert text == "我曾对美诺说：“你一定觉得我很幸运”。你怎么看？"
    assert cited == ["socrates-meno-aaaa1111"]
    assert checks == [{"chunk_id": "socrates-meno-aaaa1111", "text": "You must think me very fortunate",
                       "translation": "你一定觉得我很幸运", "ok": True, "reason": "verified"}]


def test_translated_quote_with_invented_src_becomes_paraphrase():
    text, cited, checks = run('<q src="The unexamined life is not worth living" id="socrates-meno-aaaa1111">'
                              '未经审视的人生不值得过</q>')
    assert (text, cited) == ("未经审视的人生不值得过", [])
    assert checks[0]["reason"] == "not_in_passages" and checks[0]["translation"] == "未经审视的人生不值得过"


def test_translated_quote_cannot_use_speaker_uncertain_line():
    _, cited, checks = run('<q src="let me ask a question of you">让我问你一个问题</q>')
    assert cited == [] and checks[0]["reason"] == "speaker_uncertain"


def notes_run(reply, step=None):
    f = LeadingNotesFilter()
    pieces = [reply] if step is None else [reply[i:i + step] for i in range(0, len(reply), step)]
    return "".join(f.feed(p) for p in pieces) + f.close(), f.dropped


@pytest.mark.parametrize("step", [None, 1, 4])
def test_leading_notes_block_is_dropped(step):
    reply = '<reasoning id="r1">Quote the Apology. Short.</reasoning_effort>\n\n我不敢说自己知道答案。'
    assert notes_run(reply, step) == ("我不敢说自己知道答案。", True)


@pytest.mark.parametrize("reply", ["Plain reply.", '<q id="x">a quote</q> then text', "3 < 5, surely?",
                                   "  leading spaces kept"])
def test_replies_without_leading_notes_pass_unchanged(reply):
    assert notes_run(reply, 1) == (reply, False)


def test_unclosed_leading_block_is_let_through():
    assert notes_run("<draft>never closed but it is the reply") == ("<draft>never closed but it is the reply", False)
