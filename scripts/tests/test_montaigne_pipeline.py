"""Unit tests for montaigne_pipeline.py (no network; small HTML samples)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import montaigne_pipeline as mp  # noqa: E402

# A cut-down copy of the Project Gutenberg #3600 HTML layout.
PAGE = """<html><body>
<h2>PREFACE</h2><p>The present publication is intended to supply a deficiency.</p>
<pre xml:space="preserve">
                       THE LETTERS OF MONTAIGNE.
</pre>
<p><a name="link2H_4_0003" id="link2H_4_0003"></a></p>
<h2>I.&mdash;&mdash;To Monsieur de MONTAIGNE</h2>
<p>&mdash;[This letter first appeared in the edition of 1571.]&mdash;</p>
<p>As to his last words, doubtless, if any man can give good account of them, it is I.</p>
<p>Your humble servant, MONTAIGNE.</p>
<pre xml:space="preserve">
            THE AUTHOR TO THE READER.
</pre>
<p>&mdash;[Omitted by Cotton.]&mdash;</p>
<p>READER, thou hast here an honest book.</p>
<h2>BOOK THE FIRST</h2>
<p><a name="link2HCH0002" id="link2HCH0002"></a></p>
<h2>CHAPTER II&mdash;&mdash;OF SORROW</h2>
<p>No man living is more free from this passion than I,&mdash;[Florio&rsquo;s version
reads otherwise. D.W.]&mdash;who yet neither like it in myself nor admire it in others,
having first lost seven sons, transformed into a rock&mdash;</p>
<pre xml:space="preserve">
               &ldquo;Diriguisse malis,&rdquo;

     [&ldquo;Petrified with her misfortunes.&rdquo;&mdash;Ovid, Met., vi. 304.]
</pre>
<p>thereby to express that melancholic, dumb, and deaf stupefaction.</p>
<p>Light griefs, says he, &ldquo;Curae leves loquuntur, ingentes stupent.&rdquo;
[&ldquo;Light griefs can speak: deep sorrows are dumb.&rdquo;&mdash;Seneca, Hippolytus.]
And so I think.</p>
<p><a name="link2HCH0019" id="link2HCH0019"></a></p>
<h2>CHAPTER XIX&mdash;&mdash;THAT TO STUDY PHILOSOPY IS TO LEARN TO DIE</h2>
<p>What matter is it, you will say, which way it comes to pass, provided a man does
not terrify himself with the expectation? For my part, I am of this mind, and if a man
could by any means avoid it, though by creeping under a calf&rsquo;s skin, I am one
that should not be ashamed of the shift.</p>
<p>He chose to kill himself rather than fall into the hands of the enemy.</p>
<h2>BOOK THE SECOND</h2>
<h1>CHAPTER XII. &mdash; APOLOGY FOR RAIMOND SEBOND.</h1>
<p>Plutarch gives a like example. <i>Satius est supervacua discere, quam nihil.</i>
&ldquo;&lsquo;Tis better to learn more than necessary than nothing at all.&rdquo;</p>
<pre xml:space="preserve">
   Iners malorum remedium ignorantia est.

   &ldquo;Ignorance is but a dull remedy for evils.&rdquo;
 </pre>
<h2>APOLOGY:</h2>
<p>[In fact, the first edition of the Essays has very few quotations.]</p>
<h2>PROJECT GUTENBERG EDITOR&rsquo;S BOOKMARKS:</h2>
<pre xml:space="preserve">
     A child should not be brought up in his mother&rsquo;s lap
</pre>
</body></html>"""


class Parsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stats = {}
        cls.turns = mp.parse_montaigne(PAGE, cls.stats)
        cls.by_section = {}
        for t in cls.turns:
            cls.by_section.setdefault(t.section, []).append(t)

    def test_sections_and_front_matter(self):
        self.assertEqual(list(self.by_section), [
            "Letter I: To Monsieur de Montaigne",
            "To the Reader",
            "Book I, Chapter II: Of Sorrow",
            "Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die",
            "Book II, Chapter XII: Apology for Raimond Sebond",
        ])
        all_text = " ".join(t.text for t in self.turns)
        for gone in ("present publication", "first edition", "mother’s lap", "Omitted"):
            self.assertNotIn(gone, all_text)

    def test_letters(self):
        (t,) = self.by_section["Letter I: To Monsieur de Montaigne"]
        self.assertEqual(t.work_id, "letters")
        self.assertEqual(t.addressee, "his father")
        self.assertTrue(t.text.startswith("As to his last words"))   # note and signature dropped

    def test_notes_removed_and_verse_translated(self):
        sorrow = self.by_section["Book I, Chapter II: Of Sorrow"]
        self.assertEqual(len(sorrow), 2)       # verse + lowercase paragraph joined
        a = sorrow[0].text
        self.assertNotIn("Florio", a)
        self.assertNotIn("Diriguisse", a)
        self.assertIn("than I, who yet neither", a)
        self.assertIn("rock— “Petrified with her misfortunes.” thereby to express", a)

    def test_inline_quote_replaced_by_translation(self):
        b = self.by_section["Book I, Chapter II: Of Sorrow"][1].text
        self.assertEqual(b, "Light griefs, says he, “Light griefs can speak: deep sorrows are dumb.” And so I think.")

    def test_apology_layout(self):
        (t,) = self.by_section["Book II, Chapter XII: Apology for Raimond Sebond"]
        self.assertNotIn("Satius", t.text)
        self.assertNotIn("Iners", t.text)
        self.assertIn("“‘Tis better to learn more than necessary than nothing at all.”", t.text)
        self.assertTrue(t.text.endswith("“Ignorance is but a dull remedy for evils.”"))

    def test_source_url_has_chapter_anchor(self):
        t = self.by_section["Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die"][0]
        self.assertIn(mp.SOURCE["commit"], t.source_url)
        self.assertTrue(t.source_url.endswith("#link2HCH0019"))

    def test_sensitive(self):
        kill = self.by_section["Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die"][1]
        self.assertIn("suicide", kill.sensitive)
        self.assertIn("grief", self.by_section["Book I, Chapter II: Of Sorrow"][1].sensitive)


class Language(unittest.TestCase):
    def test_is_foreign(self):
        for s in ("Contorta et aculeata sophismata,", "Eritis sicut Dii, scientes bonum et malum.",
                  "Avau le dent,"):
            self.assertTrue(mp.is_foreign(s), s)
        for s in ("Lame men perform best.", "She let me go,", "Let us go, citizens,",
                  "That they were then by one day happier than he."):
            self.assertFalse(mp.is_foreign(s), s)

    def test_translation_of(self):
        self.assertEqual(mp.translation_of("“Petrified with her misfortunes.”—Ovid, Met., vi. 304."),
                         "“Petrified with her misfortunes.”")
        self.assertIsNone(mp.translation_of("Plutarch, Life of Pompey, c. i."))
        self.assertIsNone(mp.translation_of("“Montaigne stops here to excuse himself.”—Coste."))

    def test_title_case(self):
        self.assertEqual(mp.title_case("OF THE INEQUALITY AMOUNGST US."), "Of the Inequality Amongst Us")
        self.assertEqual(mp.title_case("TO-MORROW’S A NEW DAY"), "To-Morrow’s a New Day")


class Objections(unittest.TestCase):
    def test_unquoted_cue(self):
        (o,) = mp.all_objections("What matter is it, you will say, which way it comes to pass? For my part, no.")
        self.assertEqual(o[2], "What matter is it which way it comes to pass?")

    def test_cue_at_start_cut_at_semicolon(self):
        text = "You will tell me that he was a braggadocio; I believe so too. But virtue is valid."
        (o,) = mp.all_objections(text)
        self.assertEqual(o[2], "He was a braggadocio.")
        self.assertTrue(text[o[1]:].strip().startswith("I believe so too"))

    def test_says_one_of_the_ancients_is_not_a_cue(self):
        self.assertEqual(mp.find_objections("“That must be judge of all my years,” says one of the ancients."), [])

    def test_sft_example(self):
        turns = mp.parse_montaigne(PAGE)
        sft = mp.build_sft(turns, min_words=10)
        self.assertEqual(len(sft), 1)
        ex = sft[0]
        self.assertEqual(ex["messages"][1]["content"],
                         "Reader: What matter is it which way it comes to pass, provided a man does "
                         "not terrify himself with the expectation?")
        self.assertTrue(ex["messages"][2]["content"].startswith("For my part, I am of this mind"))
        self.assertEqual(ex["meta"]["source"], "objection")
        self.assertEqual(ex["meta"]["split"], "train")

    def test_eval_split_by_chapter(self):
        t = mp.parse_montaigne(PAGE)[0]
        t.section = "Book III, Chapter X: Of Managing the Will"
        self.assertTrue(mp.is_eval(t))
        t.section = "Book III, Chapter XIII: Of Experience"
        self.assertFalse(mp.is_eval(t))


class Passages(unittest.TestCase):
    def test_ids_size_and_context(self):
        turns = mp.parse_montaigne(PAGE)
        passages = mp.build_passages(turns, 20)
        self.assertTrue(all(p["montaigne_words"] <= 20 for p in passages))
        self.assertTrue(all(p["id"].split("-")[0] in ("essays", "letters") for p in passages))
        self.assertTrue(all(len(p["id"].split("-")[1]) == 8 for p in passages))
        self.assertEqual(len({p["id"] for p in passages}), len(passages))
        again = mp.build_passages(mp.parse_montaigne(PAGE), 20)
        self.assertEqual([p["id"] for p in passages], [p["id"] for p in again])   # stable ids
        sections = mp.add_suicide_context(turns, passages)
        self.assertIn("essays|Book I, Chapter XIX: That to Study Philosophy Is to Learn to Die", sections)
        sorrow = [p for p in passages if p["section"].endswith("Of Sorrow")]
        self.assertFalse(any("suicide_context" in p["sensitive"] for p in sorrow))

    def test_split_words_prefers_semicolons(self):
        text = " ".join(["word"] * 12) + "; " + " ".join(["more"] * 12) + "."
        pieces = mp.split_words(text, 20)
        self.assertTrue(pieces[0].endswith(";"))


if __name__ == "__main__":
    unittest.main()
