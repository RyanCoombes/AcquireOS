"""Command line: acquireos <command> ...

Run `acquireos --help` for the list. Inside Docker:
    docker exec -it acquireos acquireos import-companies /data/raw/targets.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, scoring
from .importers import companies, notes, psc
from .ownership import rebuild


def main(argv=None):
    ap = argparse.ArgumentParser(prog="acquireos", description="AcquireOS data tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Create or update the database tables")

    p = sub.add_parser("import-companies", help="Import a company list (CSV or Excel)")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--sheet")

    p = sub.add_parser("import-notes", help="Import your notes, ratings and decisions (CSV or Excel)")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--sheet")

    p = sub.add_parser("import-psc", help="Import owners from the Companies House PSC snapshot (.txt or .zip)")
    p.add_argument("files", nargs="+", type=Path)

    p = sub.add_parser("preview", help="Show how a file's columns would be read, without importing")
    p.add_argument("kind", choices=["companies", "notes"])
    p.add_argument("file", type=Path)
    p.add_argument("--sheet")

    sub.add_parser("rebuild", help="Recompute ownership, links and scores")
    sub.add_parser("demo", help="Load a fictional demo dataset (for trying the app out)")
    sub.add_parser("rescore", help="Recompute scores against the active buy box")

    a = ap.parse_args(argv)
    if a.cmd == "migrate":
        print("Applied:", db.migrate() or "nothing new")
        return
    db.migrate()
    if a.cmd == "preview":
        mod = companies if a.kind == "companies" else notes
        r = mod.preview(a.file, a.sheet)
        print(json.dumps({"rows": r["row_count"], "mapping": r["mapping"], "problems": r["problems"]}, indent=2, default=str))
        return
    with db.conn() as c:
        if a.cmd == "import-companies":
            for f in a.files:
                _print(f, companies.run(c, f, sheet=a.sheet))
            rebuild(c)
        elif a.cmd == "import-notes":
            for f in a.files:
                _print(f, notes.run(c, f, sheet=a.sheet))
        elif a.cmd == "import-psc":
            print("Streaming the PSC snapshot. On a Raspberry Pi this can take a while.", file=sys.stderr)
            _print(a.files[0], psc.run(c, a.files))
        elif a.cmd == "demo":
            import tempfile

            from .demo import generate

            d = generate(Path(tempfile.mkdtemp()))
            _print(d / "companies.csv", companies.run(c, d / "companies.csv", source="demo data"))
            _print(d / "psc.jsonl", psc.run(c, [d / "psc.jsonl"]))
            _print(d / "notes.csv", notes.run(c, d / "notes.csv", source="demo notes"))
        elif a.cmd == "rebuild":
            print(rebuild(c))
        n = scoring.rescore(c)
        print(f"Scored {n} companies.")


def _print(f, r):
    msgs = r.pop("messages", [])
    print(f"{f.name}: {json.dumps(r, default=str)}")
    for m in msgs[:10]:
        print("  ", m)
    if len(msgs) > 10:
        print(f"   …and {len(msgs) - 10} more")


if __name__ == "__main__":
    main()
