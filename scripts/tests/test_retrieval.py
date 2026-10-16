"""Run: python -m unittest discover -s tests  (from the folder holding retrieval.py)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sqlite as bs  # noqa: E402
import retrieval  # noqa: E402

PASSAGES = [
    dict(id="meno-00001-00002", author="Plato", work="Meno", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Meno", "Socrates"], socrates_words=8, sensitive=[],
         source_url="u1", text="Meno: Can virtue be taught?\nSocrates: I do not know what virtue is."),
    dict(id="phaedo-00001-00002", author="Plato", work="Phaedo", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Socrates"], socrates_words=12, sensitive=["death", "suicide"],
         source_url="u2", text="Socrates: A man should not take his own life; virtue is taught by the gods."),
    dict(id="republic-00003-00004", author="Plato", work="Republic", translator="Jowett", section="Book I",
         turn_range=[3, 4], speakers=["Socrates"], socrates_words=6, sensitive=[],
         source_url="u3", text="Socrates: Justice and virtue, then, are the excellence of the soul."),
    dict(id="lysis-00000-00001", author="Plato", work="Lysis", translator="Jowett", section="Lysis Or, Friendship",
         turn_range=[0, 1], speakers=["Socrates"], socrates_words=5, sensitive=[],
         source_url="u4", text="Socrates: What is a friend?"),
]


class RetrieveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "rag_passages.jsonl").write_text("\n".join(json.dumps(p) for p in PASSAGES), encoding="utf-8")
        (tmp / "turns.jsonl").write_text("", encoding="utf-8")
        cls.db = tmp / "t.db"
        bs.main(["build", "--persona", "socrates", "--processed", str(tmp), "--db", str(cls.db)])
        os.environ["PHILOCAFE_DB"] = str(cls.db)

    def test_chunk_contract(self):
        chunks = retrieval.retrieve("socrates", "virtue taught", k=5)
        self.assertTrue(chunks)
        keys = {"chunk_id", "persona", "work", "section", "text", "source_url", "score", "sensitive"}
        for c in chunks:
            self.assertEqual(set(c), keys)
            self.assertTrue(c["chunk_id"].startswith("socrates-"))
            self.assertEqual(c["persona"], "socrates")
            self.assertTrue(c["section"])
        scores = [c["score"] for c in chunks]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_section_fallback(self):
        by_work = {c["work"]: c for c in retrieval.retrieve("socrates", "virtue friend", k=10)}
        self.assertEqual(by_work["Meno"]["section"], "turns 2-3")
        self.assertEqual(by_work["Republic"]["section"], "Book I")
        self.assertEqual(by_work["Lysis"]["section"], "turns 1-2")

    def test_sensitive_kept_and_filterable(self):
        hits = retrieval.retrieve("socrates", "take his own life", k=5)
        phaedo = [c for c in hits if c["work"] == "Phaedo"]
        self.assertEqual(phaedo[0]["sensitive"], ["death", "suicide"])
        hits = retrieval.retrieve("socrates", "take his own life", k=5, exclude_flags=("suicide",))
        self.assertNotIn("Phaedo", [c["work"] for c in hits])

    def test_unknown_persona_and_no_match(self):
        with self.assertRaises(ValueError):
            retrieval.retrieve("epictetus", "virtue")
        self.assertEqual(retrieval.retrieve("socrates", "zzzqqq"), [])
        self.assertEqual(retrieval.retrieve("socrates", "   "), [])


if __name__ == "__main__":
    unittest.main()
