"""Run: python3 -m unittest discover -s tests  (from the scripts folder)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socrates_pipeline as sp  # noqa: E402

PG_SAMPLE = """﻿The Project Gutenberg eBook of The Memorabilia, by Xenophon

Translator: H. G. Dakyns

*** START OF THE PROJECT GUTENBERG EBOOK THE MEMORABILIA ***

THE MEMORABILIA

Translated by H. G. Dakyns

CONTENTS

BOOK I

I have often wondered by what arguments those who indicted
Socrates could have persuaded the Athenians (1) that his life
was forfeit to the state.

(1) See Plato, "Apology."

He was constantly in public, _for_ he went to the walks.[2]

[Footnote 2: A note that must go.]

*** END OF THE PROJECT GUTENBERG EBOOK THE MEMORABILIA ***

License text that must go.
"""

SE_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<article id="demo"><section id="demo-introduction"><p>Jowett's introduction.</p></section>
<section id="demo-text" epub:type="z3998:drama">
<section id="demo-dramatis-personae" epub:type="z3998:dramatis-personae"><ul><li><p>Socrates</p></li><li><p>Meno</p></li></ul></section>
<table><tbody>
<tr><td epub:type="z3998:persona">Meno</td><td>Can you tell me, Socrates, whether virtue can be taught?<a href="endnotes.xhtml#note-1" epub:type="noteref">1</a></td></tr>
<tr><td epub:type="z3998:persona">Socrates</td><td>I do not even know what virtue is.</td></tr>
</tbody></table>
<p>And so on, still Socrates.</p>
</section></article></body></html>"""

NARRATED_SAMPLE = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<article id="nar"><section id="nar-text" epub:type="z3998:fiction">
<section epub:type="z3998:dramatis-personae"><ul><li><p>Socrates, who is the narrator</p></li><li><p>Glaucon</p></li></ul></section>
<p>And what is justice, Glaucon? I said.</p>
<p>I do not know, he replied.</p>
<p>Shall we look for it together?</p>
<p>By all means.</p>
</section></article></body></html>"""


class GutenbergTests(unittest.TestCase):
    def test_clean(self):
        paras = sp.clean_gutenberg(PG_SAMPLE)
        text = "\n".join(paras)
        self.assertEqual(paras[0], "§BOOK I")
        self.assertIn("persuaded the Athenians that his life", text)
        self.assertIn("for he went to the walks.", text)
        for junk in ("START OF", "License", "(1)", "Footnote", "[2]", "CONTENTS", "_"):
            self.assertNotIn(junk, text)

    def test_title_check(self):
        meta = dict(sp.XENOPHON_WORKS["xen_apology"])
        with self.assertRaises(ValueError):
            sp.parse_xenophon("xen_apology", meta, PG_SAMPLE, "u")
        turns = sp.parse_xenophon("xen_memorabilia", sp.XENOPHON_WORKS["xen_memorabilia"], PG_SAMPLE, "u")
        self.assertEqual(turns[0].section, "BOOK I")


class PlatoTests(unittest.TestCase):
    def test_drama(self):
        turns = sp.parse_plato("demo", dict(title="Demo", mode="drama"), SE_SAMPLE)
        self.assertEqual([t.speaker for t in turns], ["Meno", "Socrates"])
        self.assertTrue(turns[0].text.endswith("taught?"))          # noteref removed
        self.assertTrue(turns[1].text.endswith("still Socrates."))   # continuation
        self.assertNotIn("introduction", " ".join(t.text for t in turns))

    def test_narrated(self):
        turns = sp.parse_plato("nar", dict(title="Nar", mode="narrated"), NARRATED_SAMPLE)
        self.assertEqual([t.speaker for t in turns], ["Socrates", "Glaucon", "Socrates", "Glaucon"])
        self.assertEqual(turns[0].text, "And what is justice, Glaucon?")
        self.assertEqual(turns[1].text, "I do not know.")

    def test_sft(self):
        turns = sp.parse_plato("demo", dict(title="Demo", mode="drama"), SE_SAMPLE)
        ex = sp.build_sft(turns, include_inferred=False, context=6, min_words=1)
        self.assertEqual(len(ex), 1)
        self.assertEqual([m["role"] for m in ex[0]["messages"]], ["system", "user", "assistant"])


LONG = " ".join(["Justice is a kind of bargain between the strong and the weak."] * 15)
NARRATED_LONG = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<article id="nar"><section id="nar-text" epub:type="z3998:fiction">
<section epub:type="z3998:dramatis-personae"><ul><li><p>Socrates, who is the narrator</p></li><li><p>Glaucon</p></li>
<li><p>And others who are mute auditors.</p></li></ul></section>
<p>What do they say, Glaucon? I asked.</p>
<p>And he replied: They say this.</p>
<p>{LONG}</p>
<p>Heavens! my dear Glaucon, how energetically you polish them up, I said.</p>
</section></article></body></html>""".encode()

MONOLOGUE = b"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
<article id="mono"><section id="mono-text" epub:type="z3998:fiction">
<p>Men of Athens, I will make my defence.</p>
<p>Come hither, Meletus, and let me ask you: you think a great deal about the youth?</p>
<p>Yes, I do.</p>
<p>Tell the judges, then, who is their improver.</p>
<p>The laws.</p>
<p>I have said enough in answer to the charge of Meletus.</p>
</section></article></body></html>"""
MONO_META = dict(title="Mono", mode="monologue",
                 exchanges=[dict(start="Come hither, Meletus", end="I have said enough", partner="Meletus")])


class ReviewFixTests(unittest.TestCase):
    def test_persona_names(self):
        self.assertEqual(sp.persona_names("And others who are mute auditors."), set())
        self.assertEqual(sp.persona_names("Socrates, who is the narrator"), {"Socrates"})
        self.assertEqual(sp.persona_names("Nicias, Laches, Socrates"), {"Nicias", "Laches", "Socrates"})
        self.assertEqual(sp.persona_names("Cleinias (a Cretan)"), {"Cleinias"})
        self.assertEqual(sp.persona_names("An Athenian Stranger"), set())

    def test_long_untagged_paragraph_is_not_assumed_socrates(self):
        turns = sp.parse_plato("nar", dict(title="Nar", mode="narrated"), NARRATED_LONG)
        self.assertEqual([(t.speaker, t.attribution) for t in turns],
                         [("Socrates", "tagged"), ("Glaucon", "tagged"),
                          ("Socrates", "inferred"), ("Socrates", "tagged")])
        self.assertEqual(turns[1].text, "They say this.")
        self.assertNotIn("And", {t.speaker for t in turns})
        # the inferred speaker is not named in the RAG passage
        text = "\n".join(p["text"] for p in sp.build_passages(turns, 400))
        self.assertIn("[speaker uncertain] Justice", text)
        self.assertNotIn("Socrates: Justice", text)

    def test_subtitle_is_not_a_section(self):
        xhtml = NARRATED_LONG.replace(b'<section epub:type="z3998:dramatis-personae">',
                                      b'<hgroup><h3>Nar</h3><p>Nar Or, Friendship</p></hgroup><section epub:type="z3998:dramatis-personae">')
        turns = sp.parse_plato("nar", dict(title="Nar", mode="narrated"), xhtml)
        self.assertEqual({t.section for t in turns}, {""})

    def test_monologue_exchange(self):
        turns = sp.parse_plato("mono", MONO_META, MONOLOGUE)
        self.assertEqual([(t.speaker, t.attribution) for t in turns],
                         [("Socrates", "explicit"), ("Socrates", "inferred"), ("Meletus", "inferred"),
                          ("Socrates", "inferred"), ("Meletus", "inferred"), ("Socrates", "explicit")])

    def test_long_turns_are_split(self):
        turns = sp.parse_plato("nar", dict(title="Nar", mode="narrated"), NARRATED_LONG)
        passages = sp.build_passages(turns, 60)
        self.assertTrue(all(len(p["text"].split()) <= 60 for p in passages))
        self.assertEqual(len({p["id"] for p in passages}), len(passages))
        self.assertTrue(all(re.fullmatch(r"nar-[0-9a-f]{8}", p["id"]) for p in passages))
        self.assertEqual([p["id"] for p in passages], [p["id"] for p in sp.build_passages(turns, 60)])
        self.assertEqual(" ".join(sp.split_words(LONG, 50)), LONG)

    def test_ids_survive_turn_renumbering(self):
        turns = sp.parse_plato("nar", dict(title="Nar", mode="narrated"), NARRATED_LONG)
        before = [p["id"] for p in sp.build_passages(turns, 60)]
        shifted = [sp.Turn(**{**{k: v for k, v in vars(t).items() if k != "words"}, "idx": t.idx + 7})
                   for t in turns]
        self.assertEqual([p["id"] for p in sp.build_passages(shifted, 60)], before)

    def test_strip_all_tag_verbs(self):
        self.assertEqual(sp.strip_tags("What is justice? I asked."), "What is justice?")
        self.assertEqual(sp.strip_tags("Let us go on, I proceeded, to the next."), "Let us go on, to the next.")

    def test_sft_split_and_max_words(self):
        turns = sp.parse_plato("demo", dict(title="Demo", mode="drama"), SE_SAMPLE)
        ex = sp.build_sft(turns, include_inferred=False, context=6, min_words=1, eval_works=("demo",))
        self.assertEqual(ex[0]["meta"]["split"], "eval")
        self.assertEqual(sp.build_sft(turns, False, 6, min_words=1, max_words=5), [])


if __name__ == "__main__":
    unittest.main()
