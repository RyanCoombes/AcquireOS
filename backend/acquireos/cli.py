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
from .importers import accounts, companies, notes, psc
from .ownership import rebuild


def main(argv=None):
    ap = argparse.ArgumentParser(prog="acquireos", description="AcquireOS data tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Create or update the database tables")

    p = sub.add_parser("import-companies", help="Import or refresh a company list (CSV or Excel)")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--sheet")
    p.add_argument("--only-existing", action="store_true",
                   help="Only update companies already in your list (use with the full Companies House bulk file)")

    p = sub.add_parser("import-notes", help="Import your notes, ratings and decisions (CSV or Excel)")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--sheet")

    p = sub.add_parser("import-accounts", help="Import filed accounts (iXBRL) from Companies House accounts zips")
    p.add_argument("files", nargs="+", type=Path)

    p = sub.add_parser("fetch", help="Download and load Companies House bulk data")
    p.add_argument("what", choices=["company-data", "accounts", "psc", "all"])
    p.add_argument("--months", type=int, default=1, help="Months of accounts to load, newest first (default 1)")
    p.add_argument("--reread", action="store_true", help="Read again months loaded before newer figures were added")
    p.add_argument("--keep", action="store_true", help="Keep downloaded files instead of deleting them")

    sub.add_parser("scheduler", help="Run the monthly refresh on a schedule (used by the Docker stack)")
    sub.add_parser("geocode", help="Look up map locations for postcodes not yet located (uses postcodes.io)")
    sub.add_parser("new-token", help="Print a new random API token to put in API_TOKEN")

    p = sub.add_parser("import-psc", help="Import owners from the Companies House PSC snapshot (.txt or .zip)")
    p.add_argument("files", nargs="+", type=Path)

    p = sub.add_parser("preview", help="Show how a file's columns would be read, without importing")
    p.add_argument("kind", choices=["companies", "notes"])
    p.add_argument("file", type=Path)
    p.add_argument("--sheet")

    sub.add_parser("rebuild", help="Recompute ownership, links and scores")
    sub.add_parser("demo", help="Load a fictional demo dataset (for trying the app out)")
    sub.add_parser("rescore", help="Recompute scores against the active buy box")
    sub.add_parser("score-pending", help="Score buy boxes marked as needing it (used by the web app)")
    p = sub.add_parser("ch-details", help="Fetch Companies House API details (needs CH_API_KEY) for your pipeline or top targets")
    p.add_argument("--scope", choices=["pipeline", "targets"], default="pipeline")
    p.add_argument("--limit", type=int, default=200)

    a = ap.parse_args(argv)
    if a.cmd == "new-token":
        import secrets

        print(secrets.token_urlsafe(32))
        return
    if a.cmd == "scheduler":
        from .fetch import scheduler

        scheduler()
        return
    if a.cmd == "ch-details":
        from . import chapi, jobs

        with db.conn(dedicated=True) as c:
            if a.scope == "pipeline":
                nums = [r["company_number"] for r in c.execute(
                    """select company_number from user_company where user_id = 1
                       and status not in ('new', 'passed', 'rejected') order by updated_at desc limit %s""", (a.limit,))]
            else:
                nums = [r["company_number"] for r in c.execute(
                    """select cb.company_number from company_best cb
                       where not exists (select 1 from user_company uc where uc.company_number = cb.company_number
                                         and uc.status in ('passed', 'rejected'))
                       order by cb.score desc limit %s""", (a.limit,))]
            job = jobs.Job("ch-details", ["Companies House details"])
            job.stage("Companies House details")
            done = 0
            try:
                for i, num in enumerate(nums):
                    job.check_cancel()
                    chapi.fetch(c, num)
                    c.commit()
                    done += 1
                    job.progress((i + 1) / max(len(nums), 1), f"{i + 1:,} of {len(nums):,} companies")
                job.finish({"companies": done})
            except jobs.Cancelled:
                job.finish({"companies": done}, status="cancelled")
            except Exception as e:
                job.finish({"companies": done}, status="failed", error=str(e))
                raise
        return
    if a.cmd == "score-pending":
        from .api import score_pending

        with db.conn(dedicated=True) as c:
            print(score_pending(c))
        return
    if a.cmd == "migrate":
        print("Applied:", db.migrate() or "nothing new")
        return
    db.migrate()
    if a.cmd == "preview":
        mod = companies if a.kind == "companies" else notes
        r = mod.preview(a.file, a.sheet)
        print(json.dumps({"rows": r["row_count"], "mapping": r["mapping"], "problems": r["problems"]}, indent=2, default=str))
        return
    with db.conn(dedicated=True) as c:
        if a.cmd == "import-companies":
            for f in a.files:
                _print(f, companies.run(c, f, sheet=a.sheet, only_existing=a.only_existing))
            rebuild(c)
        elif a.cmd == "import-notes":
            for f in a.files:
                _print(f, notes.run(c, f, sheet=a.sheet))
        elif a.cmd == "geocode":
            from . import geo

            print(geo.geocode(c))
            return
        elif a.cmd == "import-accounts":
            _print(a.files[0], accounts.run(c, a.files))
        elif a.cmd == "fetch":
            from . import fetch

            if a.what == "company-data":
                _print(Path("company data"), fetch.fetch_company_data(c, keep=a.keep))
            elif a.what == "accounts":
                for r in fetch.fetch_accounts(c, plan=fetch.accounts_plan(c, a.months, reread_old=a.reread), keep=a.keep):
                    print(r)
            elif a.what == "psc":
                _print(Path("owners"), fetch.fetch_psc(c, keep=a.keep))
            else:
                c.commit()
                print(fetch.run_job("refresh", accounts_months=a.months, reread_old=a.reread))
                return
            rebuild(c)
        elif a.cmd == "import-psc":
            print("Streaming the PSC snapshot. On a Raspberry Pi this can take a while.", file=sys.stderr)
            _print(a.files[0], psc.run(c, a.files))
        elif a.cmd == "demo":
            import tempfile

            from .demo import generate

            d = generate(Path(tempfile.mkdtemp()))
            _print(d / "companies.csv", companies.run(c, d / "companies.csv", source="demo data"))
            from .demo import generate_accounts

            acc = generate_accounts(d, d / "companies.csv")
            print("accounts:", {k: v for k, v in accounts.run(c, [acc]).items() if k != "messages"})
            _print(d / "psc.jsonl", psc.run(c, [d / "psc.jsonl"]))
            _print(d / "notes.csv", notes.run(c, d / "notes.csv", source="demo notes"))
            _print(d / "companies_update.csv", companies.run(c, d / "companies_update.csv", source="demo refresh",
                                                             only_existing=True))
            from .demo import seed_geo

            print("demo map locations:", seed_geo(c))
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
