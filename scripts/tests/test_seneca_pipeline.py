"""Unit tests for seneca_pipeline.py (no network; small XHTML samples)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import seneca_pipeline as sp  # noqa: E402

HEAD = ('<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<head><title>{title}</title></head><body>')

LETTER = (HEAD.format(title="Letter X: On Living to Oneself") +
          '<section id="letter-10" epub:type="chapter z3998:letter">'
          '<hgroup><h2><span>Letter</span> <span>X</span></h2><p epub:type="title">On Living to Oneself</p></hgroup>'
          '<p epub:type="z3998:salutation">Greetings from Seneca to his friend Lucilius.</p>'
          '<p>Yes, I do not change my opinion: avoid the many.<a href="endnotes.xhtml#note-1" epub:type="noteref">1</a></p>'
          '<p>“But,” you say, “why should I not live with others?” Because the crowd harms the mind, and '
          'there is no one who does not make some vice attractive to us, or stamp it upon us, or taint us '
          'unconsciously therewith.</p>'
          '<blockquote epub:type="z3998:verse"><p><span>A line of verse,</span><br/><span>and another.</span></p></blockquote>'
          '<p class="continued">which closes the thought.</p>'
          '<p>He chose his own death, and opened his veins in the bath.</p>'
          '<p epub:type="z3998:valediction">Farewell.</p>'
          '</section></body></html>').encode()

ESSAY = (HEAD.format(title="On Peace of Mind") +
         '<section id="on-peace-of-mind" epub:type="part"><h2 epub:type="title">On Peace of Mind</h2>'
         '<section id="on-peace-of-mind-chapter-1" epub:type="chapter">'
         '<hgroup><h3>I</h3><p epub:type="title">(Serenus)</p></hgroup>'
         '<p>When I examine myself, Seneca, some vices appear on the surface.</p></section>'
         '<section id="on-peace-of-mind-chapter-2" epub:type="chapter">'
         '<hgroup><h3>II</h3><p epub:type="title">(Seneca)</p></hgroup>'
         '<p>I have long been silently asking myself, my friend Serenus, what this condition is like.</p>'
         '</section></section></body></html>').encode()

BOOKS = (HEAD.format(title="On Anger") +
         '<section id="on-anger" epub:type="part"><header><h2 epub:type="title">On Anger</h2>'
         '<p epub:type="se:bridgehead">To Novatus.</p></header>'
         '<section id="on-anger-book-1" epub:type="chapter"><h3><span>Book</span> <span>I</span></h3>'
         '<section id="on-anger-book-1-chapter-3" epub:type="z3998:subchapter"><h4>III</h4>'
         '<p>“We often are angry,” says our adversary, “not with men who have hurt us.” It is true that '
         'we are angry with those who are going to hurt us, but they do already hurt us in intention, '
         'and one who is going to do an injury is already doing it.</p>'
         '</section></section></section></body></html>').encode()


class LetterParsing(unittest.TestCase):
    def setUp(self):
        self.turns = sp.letter_turns(10, LETTER)

    def test_strips_salutation_valediction_and_noterefs(self):
        texts = [t.text for t in self.turns]
        self.assertFalse(any("Greetings" in x or x == "Farewell." for x in texts))
        self.assertEqual(texts[0], "Yes, I do not change my opinion: avoid the many.")

    def test_verse_and_continued_join_previous_paragraph(self):
        self.assertEqual(len(self.turns), 3)
        self.assertTrue(self.turns[1].text.endswith("A line of verse, and another. which closes the thought."))

    def test_section_and_source(self):
        t = self.turns[0]
        self.assertEqual(t.section, "Letter X: On Living to Oneself")
        self.assertEqual((t.work_id, t.speaker, t.addressee), ("letters", "Seneca", "Lucilius"))
        self.assertIn("@" + sp.SOURCES["letters"]["commit"], t.source_url)
        self.assertTrue(t.source_url.startswith("https://cdn.jsdelivr.net/gh/"))

    def test_sensitive_flag(self):
        self.assertIn("suicide", self.turns[2].sensitive)
        self.assertNotIn("suicide", self.turns[0].sensitive)


class EssayParsing(unittest.TestCase):
    def test_serenus_chapter_is_not_seneca(self):
        turns = sp.dialogue_turns("on-peace-of-mind", ESSAY)
        self.assertEqual([t.speaker for t in turns], ["Serenus", "Seneca"])
        self.assertEqual(turns[0].section, "Chapter I")
        p = sp.build_passages(turns, 180)
        self.assertTrue(p[0]["text"].startswith("Serenus: "))
        self.assertEqual(p[0]["seneca_words"], 0)
        self.assertFalse(p[1]["text"].startswith("Seneca:"))

    def test_book_chapter_section(self):
        turns = sp.dialogue_turns("on-anger", BOOKS)
        self.assertEqual(turns[0].section, "Book I, Chapter III")
        self.assertEqual(turns[0].addressee, "Novatus")


class Objections(unittest.TestCase):
    def test_split_quote_is_joined(self):
        (start, end, obj, cue), = sp.find_objections(
            "“But,” you say, “why should I not?” Because it harms you.")
        self.assertEqual(obj, "But why should I not?")
        self.assertEqual(cue, "you say")

    def test_poet_quotation_is_not_an_objection(self):
        self.assertEqual(sp.find_objections("“Time flies,” says he, and Virgil is right."), [])

    def test_sft_examples(self):
        sft = sp.build_sft(sp.letter_turns(10, LETTER) + sp.dialogue_turns("on-anger", BOOKS))
        self.assertEqual(len(sft), 2)
        letter, essay = sft
        self.assertEqual(letter["messages"][1]["content"], "Lucilius: But why should I not live with others?")
        self.assertTrue(letter["messages"][2]["content"].startswith("Because the crowd harms the mind"))
        self.assertEqual(letter["meta"]["split"], "eval")         # every tenth letter
        self.assertEqual(essay["messages"][1]["content"],
                         "Interlocutor: We often are angry not with men who have hurt us.")
        self.assertEqual(essay["meta"]["split"], "train")
        self.assertEqual([m["role"] for m in essay["messages"]], ["system", "user", "assistant"])

    def test_topic_prompts_are_marked_synthetic(self):
        sft = sp.build_sft(sp.letter_turns(10, LETTER), with_topic_prompts=True, min_words=5)
        topic = [e for e in sft if e["meta"]["source"] == "letter_topic"]
        self.assertEqual(len(topic), 1)
        self.assertEqual(topic[0]["meta"]["attribution"], "synthetic_prompt")
        self.assertEqual(topic[0]["messages"][1]["content"], "Lucilius: Write to me on this subject: On Living to Oneself.")


class Reported(unittest.TestCase):
    def test_rewritten_user_turn_and_answer_after_anchor(self):
        prompts = [{"work_id": "letters", "section": "Letter X:",
                    "anchor": "Yes, I do not change my opinion:",
                    "user": "Lucilius: Have you changed your opinion?"},
                   {"work_id": "letters", "section": "Letter X:", "anchor": "not in the text", "user": "x"}]
        sft = sp.build_sft(sp.letter_turns(10, LETTER), min_words=3, reported=prompts)
        rep = [e for e in sft if e["meta"]["source"] == "reported"]
        self.assertEqual(len(rep), 1)                      # missing anchor is skipped with a warning
        self.assertEqual(rep[0]["messages"][1]["content"], "Lucilius: Have you changed your opinion?")
        # the answer runs to the end of the paragraph and stops before the next objection
        self.assertEqual(rep[0]["messages"][2]["content"], "Avoid the many.")
        self.assertEqual(rep[0]["meta"]["attribution"], "rewritten_report")

    def test_shipped_prompts_all_match_the_source_format(self):
        prompts = sp.load_reported(Path(sp.__file__).resolve().parent / "seneca_reported_prompts.json")
        self.assertGreater(len(prompts), 0)
        for pr in prompts:
            self.assertRegex(pr["user"], r"^(Lucilius|Interlocutor|Serenus): \S")
            self.assertIn(pr["work_id"], {"letters", *[w for w, _ in sp.DIALOGUES.values()]})


class Passages(unittest.TestCase):
    def test_ids_are_content_hashes_and_stable(self):
        turns = sp.letter_turns(10, LETTER)
        a = sp.build_passages(turns, 30)
        for t in turns:
            t.idx += 50                       # renumbering must not change ids
        b = sp.build_passages(turns, 30)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertRegex(a[0]["id"], r"^letters-[0-9a-f]{8}$")

    def test_passage_limit_and_fields(self):
        p = sp.build_passages(sp.letter_turns(10, LETTER), 30)
        self.assertTrue(all(len(x["text"].split()) <= 30 for x in p))
        for key in ("id", "author", "work", "translator", "section", "turn_range",
                    "speakers", "seneca_words", "sensitive", "source_url", "text"):
            self.assertIn(key, p[0])

    def test_suicide_context_spreads_over_section(self):
        turns = sp.letter_turns(10, LETTER)
        p = sp.build_passages(turns, 30)
        sp.add_suicide_context(turns, p)
        self.assertTrue(all("suicide_context" in x["sensitive"] for x in p))

    def test_curated_section_keys_match_exactly(self):
        self.assertTrue(sp.in_sections("marcia|Chapter XX", ["marcia|Chapter XX"]))
        self.assertFalse(sp.in_sections("marcia|Chapter XXI", ["marcia|Chapter XX"]))
        self.assertTrue(sp.in_sections("letters|Letter LXX: On the Proper Time", ["letters|Letter LXX:"]))
        self.assertFalse(sp.in_sections("letters|Letter LXXI: On the Supreme Good", ["letters|Letter LXX:"]))
        self.assertIn("suicide", sp.flag_sensitive("The harbour.", "letters|Letter LXX: On the Proper Time"))


if __name__ == "__main__":
    unittest.main()
