"""Run turns from the command line and print every UI event, for debugging.

    python -m app.cli --fake "is virtue teachable" "TEST_TIER3"

Each argument is one user turn in the same thread.
"""

from __future__ import annotations

import argparse
import json
import uuid

from app.config import load_config
from app.deps import default_deps
from app.fakes import fake_deps
from app.graph import build_graph, run_turn


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("turns", nargs="+", help="user messages, one per turn")
    ap.add_argument("--fake", action="store_true", help="use offline stand-ins for Jev, the voice model and retrieval")
    ap.add_argument("--persona", default=None)
    args = ap.parse_args(argv)

    deps = fake_deps() if args.fake else default_deps()
    persona = args.persona or load_config().default_persona
    graph = build_graph(deps)
    thread_id = uuid.uuid4().hex
    for text in args.turns:
        print(f"> {text}")
        for ev in run_turn(graph, thread_id, text, persona):
            print(json.dumps(ev, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
