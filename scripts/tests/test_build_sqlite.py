"""Run: python -m unittest discover -s tests  (from the folder holding build_sqlite.py)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_sqlite as bs  # noqa: E402

PASSAGES = [
    dict(id="meno-00001-00002", author="Plato", work="Meno", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Meno", "Socrates"], socrates_words=8, sensitive=[],
         source_url="u", text="Meno: Can virtue be taught?\nSocrates: I do not know what virtue is."),
    dict(id="phaedo-00001-00002", author="Plato", work="Phaedo", translator="Jowett", section="",
         turn_range=[1, 2], speakers=["Socrates"], socrates_words=12, sensitive=["death", "suicide"],
         source_url="u", text="Socrates: A man should not take his own life; virtue is taught by the gods."),
]
TURNS = [dict(work_id="meno", idx=1, author="Plato", work="Meno", section="", speaker="Meno",
              kind="speech", attribution="explicit", words=4, source_url="u", text="Can virtue be taught?")]
SFT = [dict(messages=[{"role": "user", "content": "Meno: Can virtue be taught?"},
                      {"role": "assistant", "content": "What is virtue?"}],
            meta=dict(work_id="meno", work="Meno", turn_idx=2, attribution="explicit", is_question=True))]


def write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


class BuildSqliteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write(self.tmp / "rag_passages.jsonl", PASSAGES)
        write(self.tmp / "turns.jsonl", TURNS)
        write(self.tmp / "socrates_sft.jsonl", SFT)
        self.db = self.tmp / "t.db"

    def build(self, embed):
        argv = ["build", "--persona", "socrates", "--processed", str(self.tmp), "--db", str(self.db)]
        bs.main(argv + (["--embed", "--model", "hash"] if embed else []))

    def test_keyword_build_is_idempotent_and_filters(self):
        self.build(False)
        self.build(False)
        con = bs.connect(self.db)
        self.assertEqual(con.execute("SELECT count(*) FROM passages").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT count(*) FROM sft_examples").fetchone()[0], 1)
        hits = bs.search(con, "virtue taught", mode="keyword")
        self.assertEqual(len(hits), 2)
        hits = bs.search(con, "virtue taught", mode="keyword", exclude_flags=("suicide",))
        self.assertEqual([h["work"] for h in hits], ["Meno"])
        self.assertEqual(bs.search(con, 'bad "fts) syntax', mode="keyword"), [])

    def test_vector_search(self):
        try:
            import sqlite_vec  # noqa: F401
        except ImportError:
            self.skipTest("sqlite-vec not installed")
        self.build(True)
        self.build(True)
        con = bs.connect(self.db, need_vec=True)
        self.assertEqual(con.execute("SELECT count(*) FROM passages_vec").fetchone()[0], 2)
        hits = bs.search(con, "take his own life", mode="vector", k=1)
        self.assertEqual(hits[0]["work"], "Phaedo")


if __name__ == "__main__":
    unittest.main()
