"""Run: python3 -m unittest discover -s tests  (from the scripts folder)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import epictetus_pipeline as ep  # noqa: E402

HEAD = (b'<?xml version="1.0" encoding="utf-8"?>\n<html xmlns="http://www.w3.org/1999/xhtml" '
        b'xmlns:epub="http://www.idpf.org/2007/ops"><body>')

BOOK_SAMPLE = HEAD + """
<section id="book-1" epub:type="chapter"><h2>Book I</h2>
<section id="chapter-1-1">
  <hgroup><h3 epub:type="z3998:ordinal z3998:roman">I</h3>
  <p epub:type="title">Of the Things Which Are in Our Power</p></hgroup>
  <p>In our power are opinion (<i xml:lang="grc">ὑπόληψις</i>), aversion (<i xml:lang="grc">ἔκκλισις</i>, turning from a thing), and desire (aim at).<a href="endnotes.xhtml#note-2" epub:type="noteref">2</a></p>
  <blockquote><p><span>Lead me, O Zeus,</span><br/><span>and thou Destiny.</span></p></blockquote>
  <p class="continued">So says Cleanthes.</p>
  <p>If you are not satisfied, the door is open.</p>
</section>
<section id="chapter-1-15">
  <hgroup><h3 epub:type="z3998:ordinal z3998:roman">XV<a href="endnotes.xhtml#note-9" epub:type="noteref">9</a></h3>
  <p epub:type="title">What Philosophy Promises</p></hgroup>
  <p>When a man was consulting him how he should persuade his brother, Epictetus replied: Philosophy does not propose to secure for a man any external thing.</p>
  <p>If a man, said Epictetus, opposes evident truths, it is not easy to change his mind.</p>
  <p>When he was visited by one of the magistrates, Epictetus inquired of him about his children. “Miserable,” the man said.</p>
  <p>When the magistrate came, Epictetus asked: “Do you love your child?” “I do.”</p>
</section>
</section></body></html>""".encode("utf-8")

FRAGMENTS_SAMPLE = HEAD + """
<article id="fragments">
<section id="fragments-introduction" epub:type="introduction"><p>These Fragments are entitled ...</p></section>
<section id="fragments-3" epub:type="chapter"><h3>III</h3><p>If you wish to be good, first believe that you are bad.</p></section>
<section id="fragments-group"><h3>From Stobaeus</h3>
  <section id="fragments-172" epub:type="chapter"><h4>CLXXII</h4><p>Epictetus being asked, What man is rich, answered, He who is content.</p></section>
</section>
<section id="fragments-179" epub:type="chapter" xml:lang="la"><header><h3>CLXXIX</h3></header><p>Philosophus in disciplina Stoica celebratus.</p></section>
</article></body></html>""".encode("utf-8")


def parse(work_id, files):
    return ep.parse_work(work_id, ep.WORKS[work_id], files)


class EpictetusPipelineTests(unittest.TestCase):
    def test_greek_glosses(self):
        self.assertEqual(ep.strip_greek("opinion (ὑπόληψις), aversion (ἔκκλισις, turning from a thing)"),
                         "opinion, aversion (turning from a thing)")
        self.assertEqual(ep.strip_greek("desire (aim at) and (αὐταρκείας）order"), "desire (aim at) and order")

    def test_discourse_sections_and_cleaning(self):
        files = {n: b"" for n in ep.WORKS["discourses"]["files"]}
        files["book-1.xhtml"] = BOOK_SAMPLE
        meta = dict(ep.WORKS["discourses"], files=["book-1.xhtml"])
        turns = ep.parse_work("discourses", meta, files)
        first = turns[0]
        self.assertEqual(first.section, "Book I, Chapter 1")
        self.assertEqual(first.chapter_title, "Of the Things Which Are in Our Power")
        self.assertNotIn("ὑπόληψις", first.text)
        self.assertNotIn("2", first.text)                   # footnote marker removed
        # verse and the "continued" paragraph stay in the same turn
        self.assertIn("Lead me, O Zeus, and thou Destiny. So says Cleanthes.", first.text)
        self.assertTrue(turns[1].text.startswith("If you are not satisfied"))
        # chapter number comes from the id even when the heading has a note marker
        self.assertEqual(turns[2].section, "Book I, Chapter 15")

    def test_arrian_frames(self):
        meta = dict(ep.WORKS["discourses"], files=["book-1.xhtml"])
        turns = ep.parse_work("discourses", meta, {"book-1.xhtml": BOOK_SAMPLE})[2:]
        got = [(t.speaker, t.attribution, t.text[:30]) for t in turns]
        self.assertEqual(got, [
            ("Arrian", "narration", "When a man was consulting him "),
            ("Epictetus", "tagged", "Philosophy does not propose to"),
            ("Epictetus", "tagged", "If a man opposes evident truth"),
            ("Arrian", "narration", "When he was visited by one of "),
            ("Arrian", "narration", "When the magistrate came, Epic"),
        ])
        self.assertTrue(turns[0].text.endswith("Epictetus replied:"))

    def test_fragments(self):
        turns = parse("fragments", {"fragments.xhtml": FRAGMENTS_SAMPLE})
        self.assertEqual([t.section for t in turns], ["Fragment 3", "Fragment 172"])
        self.assertTrue(all(t.attribution == "attributed" for t in turns))
        self.assertFalse(any("Philosophus" in t.text or "entitled" in t.text for t in turns))

    def test_passages(self):
        meta = dict(ep.WORKS["discourses"], files=["book-1.xhtml"])
        turns = ep.parse_work("discourses", meta, {"book-1.xhtml": BOOK_SAMPLE})
        passages = ep.build_passages(turns, 180)
        self.assertEqual([p["section"] for p in passages], ["Book I, Chapter 1", "Book I, Chapter 15"])
        p = passages[0]
        self.assertRegex(p["id"], r"^discourses-[0-9a-f]{8}$")
        self.assertIn("suicide", p["sensitive"])           # "the door is open"
        self.assertTrue(p["source_url"].endswith("book-1.xhtml#chapter-1-1"))
        self.assertIn(ep.SE_REPOS["discourses"]["commit"], p["source_url"])
        # Arrian's narration does not count as Epictetus' words
        self.assertLess(passages[1]["epictetus_words"], len(passages[1]["text"].split()))
        # ids depend on text only
        for t in turns:
            t.idx += 7
        self.assertEqual([q["id"] for q in ep.build_passages(turns, 180)], [q["id"] for q in passages])

    def test_long_turns_are_split(self):
        meta = dict(ep.WORKS["discourses"], files=["book-1.xhtml"])
        turns = ep.parse_work("discourses", meta, {"book-1.xhtml": BOOK_SAMPLE})
        turns[0].text = " ".join(["Remember this."] * 200)
        passages = ep.build_passages(turns, 50)
        self.assertTrue(all(len(p["text"].split()) <= 50 for p in passages))
        self.assertEqual(len({p["id"] for p in passages}), len(passages))

    def test_sensitive_euphemisms(self):
        for s in ("If the smoke is moderate, I will stay", "he gives the signal for retreat, opens the door",
                  "is it not in your power to die?", "resolved to starve himself to death"):
            self.assertIn("suicide", ep.flag_sensitive(s), s)
        self.assertNotIn("suicide", ep.flag_sensitive("I found the door shut and came back."))


if __name__ == "__main__":
    unittest.main()
