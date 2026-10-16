"""Run: python -m unittest discover -s tests  (from the socrates-data folder)."""
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


if __name__ == "__main__":
    unittest.main()
