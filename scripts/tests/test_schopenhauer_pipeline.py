"""Unit tests for schopenhauer_pipeline.py (no network; small text samples)."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schopenhauer_pipeline as sp  # noqa: E402

PG_HEAD = ("The Project Gutenberg eBook\r\n\r\n"
           "***START OF THE PROJECT GUTENBERG EBOOK TEST***\r\n\r\n")
PG_TAIL = "\r\n\r\n***END OF THE PROJECT GUTENBERG EBOOK TEST***\r\n\r\nLicence text that must not appear.\r\n"

PESSIMISM = PG_HEAD + """CONTENTS.

  ON SUICIDE
  IMMORTALITY: A DIALOGUE


NOTE.

A translator's note that is not Schopenhauer's text.

T.B.S.


ON SUICIDE.


As far as I know, none but the votaries of monotheistic religions look
upon suicide as a crime.[1]

[Footnote 1: A translator's footnote
that runs over two lines.]

  A quoted line of verse,
  and another.

*       *       *       *       *

It will generally be found that the --answer-- is _plain_.


IMMORTALITY:[1] A DIALOGUE.


THRASYMACHOS--PHILALETHES.

_Thrasymachos_. Tell me now, in one word, what shall I be after my
death?

_Philalethes_. All and nothing!

_Thrasymachos_. What do you mean?

_Philalethes_. (Aside.) German humbug, he means.

_Thrasymachos_. And then?

_Philalethes_. Transcendental knowledge is knowledge which passes beyond
the bounds of possible experience.
""" + PG_TAIL

COUNSELS = PG_HEAD + """COUNSELS AND MAXIMS.

CONTENTS.

  INTRODUCTION
  I.   GENERAL RULES


INTRODUCTION.

If my object in these pages were to present a complete scheme of counsels.


CHAPTER I.

GENERAL RULES.--SECTION 1.


The first and foremost rule for the wise conduct of life.

SECTION 2. To estimate a man's condition in regard to happiness.
""" + PG_TAIL

WWI1 = PG_HEAD + """CONTENTS

TRANSLATORS' PREFACE.

The translators speak here.

PREFACE TO THE FIRST EDITION.

I propose to point out here how this book must be read.

_Written at Dresden in August 1818._

FIRST BOOK. THE WORLD AS IDEA.

First Aspect. The Idea Subordinated To The Principle Of Sufficient Reason.

    Sors de l'enfance, ami réveille toi!

    —_Jean Jacques Rousseau._

§ 1. “The world is my idea:”—this is a truth,(1) which holds good for
everything that lives and knows.

The second paragraph of the first section.

§ 2. That which knows all things and is known by none is the subject.

FOOTNOTES

    1 F. H. Jacobi.
""" + PG_TAIL

WWI3 = PG_HEAD + """SUPPLEMENTS TO THE SECOND BOOK.

SUPPLEMENTS TO THE FOURTH BOOK.

Chapter XLVI.(41) On The Vanity And Suffering Of Life.

Awakened to life out of the night of unconsciousness, the will finds itself an individual.

APPENDIX.

Abstract written by the translators.
""" + PG_TAIL


class EssayParsing(unittest.TestCase):
    def setUp(self):
        self.turns = sp.essay_turns("pessimism", PESSIMISM)

    def test_skips_translator_note_footnotes_and_licence(self):
        text = " ".join(t.text for t in self.turns)
        for bad in ("translator", "Footnote", "Licence", "[1]", "_"):
            self.assertNotIn(bad, text)

    def test_quotation_joins_previous_paragraph(self):
        first = self.turns[0]
        self.assertEqual(first.section, "On Suicide")
        self.assertTrue(first.text.endswith("crime. A quoted line of verse, and another."))

    def test_dashes_and_italics(self):
        self.assertEqual(self.turns[1].text, "It will generally be found that the —answer— is plain.")

    def test_dialogue_speakers_and_section(self):
        dlg = [t for t in self.turns if t.section == "Immortality: A Dialogue"]
        self.assertEqual([t.speaker for t in dlg][:2], ["Thrasymachos", "Philalethes"])
        self.assertEqual(dlg[1].text, "All and nothing!")

    def test_suicide_section_flag(self):
        self.assertIn("suicide", self.turns[1].sensitive)      # whole essay flagged

    def test_counsels_chapters_and_inline_sections(self):
        turns = sp.essay_turns("counsels", COUNSELS)
        self.assertEqual([t.section for t in turns],
                         ["Introduction", "Chapter I: General Rules, Section 1",
                          "Chapter I: General Rules, Section 2"])
        self.assertTrue(turns[2].text.startswith("To estimate"))


class WWIParsing(unittest.TestCase):
    def test_vol1_sections_mottos_and_markers(self):
        turns = sp.wwi_turns("wwi1", WWI1)
        self.assertEqual([t.section for t in turns],
                         ["Preface to the First Edition",
                          "First Book: The World as Idea, § 1",
                          "First Book: The World as Idea, § 1",
                          "First Book: The World as Idea, § 2"])
        self.assertEqual(turns[1].text[:40], "“The world is my idea:”—this is a truth,")
        self.assertNotIn("Rousseau", " ".join(t.text for t in turns))   # motto dropped
        self.assertNotIn("Jacobi", " ".join(t.text for t in turns))     # footnotes cut
        self.assertEqual(turns[0].volume, "I")

    def test_vol3_chapter_heading_and_translators_appendix(self):
        turns = sp.wwi_turns("wwi3", WWI3, offset=10)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].section,
                         "Supplements to the Fourth Book, Chapter XLVI: On the Vanity and Suffering of Life")
        self.assertEqual(turns[0].idx, 10)


class Helpers(unittest.TestCase):
    def test_title_case(self):
        self.assertEqual(sp.title_case("ON THE WISDOM OF LIFE: APHORISMS."), "On the Wisdom of Life: Aphorisms")
        self.assertEqual(sp.title_case("PERSONALITY, OR WHAT A MAN IS."), "Personality, or What a Man Is")

    def test_clean_text(self):
        self.assertEqual(sp.clean_text("a [Footnote: note [Greek: x] here] b,(3) [Greek: abc] c"),
                         "a b, [Greek] c")

    def test_flags(self):
        self.assertIn("despair", sp.flag_sensitive("it would be better not to have been born"))
        self.assertIn("suicide", sp.flag_sensitive("he took his own life"))
        self.assertEqual(sp.flag_sensitive("On noise and thinking."), [])


class SFTAndPassages(unittest.TestCase):
    def setUp(self):
        self.turns = sp.essay_turns("pessimism", PESSIMISM)

    def test_dialogue_pairs_skip_asides(self):
        sft = sp.build_sft(self.turns)
        users = [e["messages"][1]["content"] for e in sft]
        self.assertEqual(users, ["Thrasymachos: And then?"])   # "All and nothing!" < 4 words; aside skipped
        self.assertEqual(sft[0]["meta"]["source"], "dialogue")
        self.assertEqual(sft[0]["meta"]["split"], "eval")       # Immortality is held out

    def test_objection(self):
        objs = sp.find_objections("“But,” you say, “why should I not live?” Because it is so.")
        self.assertEqual(objs[0][2], "But why should I not live?")
        self.assertEqual(sp.find_objections('a state of which it may be said: "It is bad to-day."'), [])

    def test_passages_are_stable_small_and_labelled(self):
        a = sp.build_passages(self.turns, 180)
        b = sp.build_passages(sp.essay_turns("pessimism", PESSIMISM), 180)
        self.assertEqual([p["id"] for p in a], [p["id"] for p in b])
        self.assertTrue(all(p["id"].startswith("pessimism-") and len(p["id"]) == len("pessimism-") + 8 for p in a))
        dlg = next(p for p in a if p["section"] == "Immortality: A Dialogue")
        self.assertTrue(dlg["text"].startswith("Thrasymachos: Tell me now"))
        self.assertIn("\nPhilalethes: All and nothing!", dlg["text"])
        self.assertLess(dlg["schopenhauer_words"], sum(len(x.split()) for x in dlg["text"].split()))

    def test_long_paragraph_is_split(self):
        t = sp.Turn(work_id="wwi", work="W", author="Schopenhauer", translator="T", source_url="u",
                    section="S", idx=0, speaker="Schopenhauer", kind="speech", attribution="explicit",
                    text=" ".join(["Word word word word word."] * 100))
        ps = sp.build_passages([t], 180)
        self.assertTrue(all(len(p["text"].split()) <= 180 for p in ps))
        self.assertGreater(len(ps), 2)

    def test_suicide_context_window_and_caution_csv(self):
        mk = lambda i, text: sp.Turn(work_id="wwi", work="W", author="Schopenhauer", translator="T",
                                     source_url="u", section="S", idx=i, speaker="Schopenhauer",
                                     kind="speech", attribution="explicit",
                                     text=text + " " + " ".join(["filler"] * 170))
        turns = [mk(i, "Nothing here.") for i in range(8)]
        turns[4] = mk(4, "He speaks of suicide.")
        for t in turns:
            t.sensitive = sp.flag_sensitive(t.text)
        ps = sp.build_passages(turns, 180)
        sp.add_suicide_context(turns, ps)
        flagged = [i for i, p in enumerate(ps) if "suicide_context" in p["sensitive"]]
        self.assertEqual(flagged, [2, 3, 4, 5, 6])
        with tempfile.TemporaryDirectory() as d:
            n = sp.write_caution_csv(Path(d) / "c.csv", ps)
            with open(Path(d) / "c.csv", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(n, 5)
        self.assertEqual([r["priority"] for r in rows].count("high"), 1)
        self.assertTrue(rows[0]["chunk_id"].startswith("schopenhauer-wwi-"))


if __name__ == "__main__":
    unittest.main()
