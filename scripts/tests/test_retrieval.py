"""Run: python3 -m unittest discover -s tests  (from the scripts folder)."""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sqlite as bs  # noqa: E402
import retrieval  # noqa: E402

try:
    import sqlite_vec  # noqa: F401
    HAS_VEC = True
except ImportError:
    HAS_VEC = False

PASSAGES = [
    dict(id="meno-3fa9c2e1", author="Plato", work="Meno", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Meno", "Socrates"], socrates_words=8, sensitive=[],
         source_url="u1", text="Meno: Can virtue be taught?\nSocrates: I do not know what virtue is."),
    dict(id="phaedo-0b1c2d3e", author="Plato", work="Phaedo", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Socrates"], socrates_words=12, sensitive=["death", "suicide"],
         source_url="u2", text="Socrates: A man should not take his own life; virtue is taught by the gods."),
    dict(id="republic-9a8b7c6d", author="Plato", work="Republic", translator="Jowett", section="Book I",
         turn_range=[3, 4], speakers=["Socrates"], socrates_words=6, sensitive=[],
         source_url="u3", text="Socrates: Justice and virtue, then, are the excellence of the soul."),
    dict(id="lysis-1f2e3d4c", author="Plato", work="Lysis", translator="Jowett", section="",
         turn_range=[0, 1], speakers=["Socrates"], socrates_words=5, sensitive=[],
         source_url="u4", text="Socrates: What is a friend?"),
]
CHUNK_KEYS = {"chunk_id", "persona", "work", "section", "text", "source_url", "score"}


def make_db(embed: bool) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "rag_passages.jsonl").write_text("\n".join(json.dumps(p) for p in PASSAGES), encoding="utf-8")
    (tmp / "turns.jsonl").write_text("", encoding="utf-8")
    db = tmp / "t.db"
    bs.main(["build", "--persona", "socrates", "--processed", str(tmp), "--db", str(db)]
            + (["--embed", "--model", "hash"] if embed else []))
    return db


@unittest.skipUnless(HAS_VEC, "sqlite-vec not installed")
class RetrieveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = make_db(embed=True)
        retrieval.close_db()
        os.environ["PHILOCAFE_DB"] = str(cls.db)

    @classmethod
    def tearDownClass(cls):
        retrieval.close_db()

    def test_chunk_contract(self):
        chunks = retrieval.retrieve("socrates", "can virtue be taught", k=5, min_score=0.0)
        self.assertTrue(chunks)
        for c in chunks:
            self.assertEqual(set(c), CHUNK_KEYS)
            self.assertRegex(c["chunk_id"], r"^socrates-[a-z]+-[0-9a-f]{8}$")
            self.assertEqual(c["persona"], "socrates")
            self.assertTrue(-1.0 <= c["score"] <= 1.0)
        scores = [c["score"] for c in chunks]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(chunks[0]["work"], "Meno")

    def test_score_is_cosine_similarity(self):
        top = retrieval.retrieve("socrates", "What is a friend?", k=1, min_score=0.0)[0]
        self.assertEqual(top["work"], "Lysis")
        emb = bs.make_embedder("hash")
        q, p = emb.encode(["What is a friend?", PASSAGES[3]["text"]])
        self.assertAlmostEqual(top["score"], bs.cosine(q, p), places=3)

    def test_section(self):
        by_work = {c["work"]: c for c in retrieval.retrieve("socrates", "virtue friend soul", k=10, min_score=-1)}
        self.assertEqual(by_work["Republic"]["section"], "Book I")
        self.assertEqual(by_work["Meno"]["section"], "")

    def test_min_score(self):
        everything = retrieval.retrieve("socrates", "virtue", k=10, min_score=-1)
        self.assertEqual(len(everything), len(PASSAGES))
        cut = everything[1]["score"]
        kept = retrieval.retrieve("socrates", "virtue", k=10, min_score=cut)
        self.assertTrue(all(c["score"] >= cut for c in kept))
        self.assertLess(len(kept), len(everything))
        self.assertEqual(retrieval.retrieve("socrates", "virtue", k=10, min_score=1.01), [])

    def test_no_relevant_passage(self):
        self.assertEqual(retrieval.retrieve("socrates", "zzzqqq xylophone"), [])
        self.assertEqual(retrieval.retrieve("socrates", "   "), [])

    def test_no_safety_filtering(self):
        works = [c["work"] for c in retrieval.retrieve("socrates", "take his own life", k=5, min_score=0.0)]
        self.assertIn("Phaedo", works)
        with self.assertRaises(TypeError):
            retrieval.retrieve("socrates", "life", exclude_flags=("suicide",))

    def test_unknown_persona(self):
        with self.assertRaises(ValueError):
            retrieval.retrieve("epictetus", "virtue")

    def test_read_only_connection(self):
        con = retrieval.open_db()
        self.assertIs(con, retrieval.open_db())
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("DELETE FROM passages")

    def test_corpus_version(self):
        self.assertRegex(retrieval.corpus_version("socrates"), r"^[0-9a-f]{12}$")
        self.assertEqual(retrieval.corpus_version("socrates"), bs.corpus_version(PASSAGES))


@unittest.skipUnless(HAS_VEC, "sqlite-vec not installed")
class NoVectorIndexTests(unittest.TestCase):
    def test_keyword_only_database_is_an_error(self):
        db = make_db(embed=False)
        retrieval.close_db()
        try:
            with self.assertRaises(RuntimeError):
                retrieval.open_db(db)
        finally:
            retrieval.close_db()


if __name__ == "__main__":
    unittest.main()
