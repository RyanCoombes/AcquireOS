"""Download Companies House bulk files and load them, by hand or monthly.

Products (all free, no account needed):
  company data   https://download.companieshouse.gov.uk/en_output.html
                 BasicCompanyDataAsOneFile-YYYY-MM-01.zip, every live company,
                 about 0.5 GB zipped and 2.6 GB unzipped, monthly.
  accounts       https://download.companieshouse.gov.uk/en_monthlyaccountsdata.html
                 Accounts_Monthly_Data-<Month><Year>.zip, every set of
                 electronically filed accounts in the month (several GB).
                 Older months: historicmonthlyaccountsdata.html
  owners (PSC)   https://download.companieshouse.gov.uk/en_pscdata.html
                 persons-with-significant-control-snapshot-YYYY-MM-DD.zip, daily.

File names change each month, so links are found by reading the listing
pages rather than being hard-coded. Large files are streamed to disk,
processed, then deleted unless keep=True, so the Pi needs room for only one
file at a time.
"""
from __future__ import annotations

import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

BASE = os.environ.get("CH_DOWNLOAD_BASE", "https://download.companieshouse.gov.uk/")
DATA_DIR = Path(os.environ.get("DATA_DIR_IN_CONTAINER", "/data")) / "companies-house"
UA = "AcquireOS/0.2 (self-hosted research tool)"

PAGES = {
    "company": ["en_output.html"],
    "accounts": ["en_monthlyaccountsdata.html", "historicmonthlyaccountsdata.html"],
    "psc": ["en_pscdata.html"],
}
PATTERNS = {
    "company": re.compile(r"BasicCompanyDataAsOneFile-(\d{4}-\d{2}-\d{2})\.zip$", re.I),
    "accounts": re.compile(r"Accounts_Monthly_Data-([A-Za-z]+)(\d{4})\.zip$", re.I),
    "psc": re.compile(r"persons-with-significant-control-snapshot-(\d{4}-\d{2}-\d{2})(?:_\d+of\d+)?\.zip$", re.I),
}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                     "august", "september", "october", "november", "december"], 1)}


# The job being run (for progress), if any. Set by run_job().
JOB = None


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] {msg}", file=sys.stderr, flush=True)
    if JOB is not None:
        JOB.log(msg)


def progress(frac: float | None = None, detail: str | None = None):
    if JOB is not None:
        JOB.progress(frac, detail)


def _loader_progress(msg: str, frac: float | None = None):
    """Callback handed to the loaders: they report a message and, where they
    can tell, the fraction done."""
    progress(frac, msg)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def links(kind: str, html_by_page: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """[(sort_key, url)] newest first, for one product."""
    out: dict[str, str] = {}
    for page in PAGES[kind]:
        page_url = urljoin(BASE, page)
        if html_by_page is not None:
            html = html_by_page.get(page, "")
        else:
            try:
                html = _get(page_url).decode("utf-8", errors="replace")
            except Exception as e:
                log(f"Could not read {page_url}: {e}")
                continue
        for href in re.findall(r'href="([^"]+)"', html):
            name = href.rsplit("/", 1)[-1]
            m = PATTERNS[kind].search(name)
            if not m:
                continue
            if kind == "accounts":
                month = MONTHS.get(m.group(1).lower())
                if not month:
                    continue
                key = f"{m.group(2)}-{month:02d}"
            else:
                key = m.group(1) + name  # keep multi-part files distinct
            out[key] = urljoin(page_url, href)
    return sorted(out.items(), reverse=True)


def _writable_dir(preferred: Path) -> Path:
    """The data folder, or a temporary folder if it cannot be written to."""
    import tempfile

    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return preferred
    except OSError as e:
        fallback = Path(tempfile.gettempdir()) / "acquireos-downloads"
        fallback.mkdir(parents=True, exist_ok=True)
        log(f"Cannot write to {preferred} ({e}); using {fallback} instead. "
            f"Fix with: sudo chown -R 1000:1000 <your DATA_DIR> on the host.")
        return fallback


def download(url: str, dest_dir: Path = DATA_DIR, report: bool = True) -> Path:
    dest_dir = _writable_dir(dest_dir)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                size = int(r.headers.get("Content-Length") or 0)
                if dest.exists() and size and dest.stat().st_size == size:
                    log(f"Already have {dest.name}")
                    return dest
                log(f"Downloading {dest.name} ({size / 1e9:.2f} GB)" if size else f"Downloading {dest.name}")
                tmp = dest.with_suffix(dest.suffix + ".part")
                got, t0 = 0, time.time()
                with open(tmp, "wb") as f:
                    while chunk := r.read(4 << 20):
                        f.write(chunk)
                        got += len(chunk)
                        if report and size:
                            rate = got / max(time.time() - t0, 0.1) / 1e6
                            progress(min(got / size, 1) * 0.15,
                                     f"Downloading {dest.name}: {got / 1e9:.2f} of {size / 1e9:.2f} GB ({rate:.0f} MB/s)")
                tmp.rename(dest)
                log(f"Downloaded {dest.name} in {time.time() - t0:.0f}s")
                return dest
        except Exception as e:
            if JOB is not None:
                JOB.check_cancel()
            wait = 2 ** (attempt + 2)
            log(f"Download failed ({e}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Could not download {url}")


def _scaled(start: float):
    """Loader progress mapped onto the part of a stage after the download."""
    def cb(msg: str, frac: float | None = None):
        progress(None if frac is None else start + (1 - start) * frac, msg)
    return cb


def fetch_company_data(conn, keep: bool = False) -> dict:
    found = links("company")
    if not found:
        raise RuntimeError("No company data file found on the Companies House download page")
    from .importers import register

    name = found[0][1].rsplit("/", 1)[-1]
    if conn.execute("""select 1 from import_run where kind = 'register' and filename = %s and finished_at is not null
                       and loader_version >= %s""", (name, register.LOADER_VERSION)).fetchone():
        log(f"Skipping {name}: this register snapshot is already loaded")
        return {"skipped": name}
    path = download(found[0][1])
    r = register.load(conn, path, full=True, progress=_scaled(0.15))
    # Delete only after a successful load: if loading fails, the file stays
    # and a re-run reuses it instead of downloading it again.
    if not keep:
        path.unlink(missing_ok=True)
    return r


def accounts_plan(conn, months: int, skip_loaded: bool = True, reread_old: bool = False) -> list[tuple[str, str, bool]]:
    """[(label, url, already_loaded)] NEWEST first, so the latest figures
    arrive first and history fills in behind them. With reread_old, months
    read by an older version of the loader (fewer figures) count as not loaded."""
    from .importers.accounts import LOADER_VERSION

    loaded = {r["filename"] for r in conn.execute(
        "select filename from import_run where kind = 'accounts' and finished_at is not null and loader_version >= %s",
        (LOADER_VERSION if reread_old else 0,))}
    chosen = links("accounts")[:months]
    out = []
    for key, url in chosen:
        name = url.rsplit("/", 1)[-1]
        y, m = key.split("-")
        label = f"Accounts: {datetime(int(y), int(m), 1):%B %Y}"
        out.append((label, url, skip_loaded and name in loaded))
    return out


def fetch_accounts(conn, months: int = 1, keep: bool = False, skip_loaded: bool = True,
                   plan: list | None = None) -> list[dict]:
    """Load the newest `months` monthly accounts files, NEWEST FIRST.

    Every figure records the balance sheet date of the filing it came from,
    and an older filing never overwrites a newer one, so the order is safe;
    newest first means the latest figures are usable straight away while
    history fills in. Changes (new accounts, staff) are only recorded for the
    newest month, so back-filling does not flood the Changes page. The next
    month downloads while this one is read."""
    from concurrent.futures import ThreadPoolExecutor

    from .importers import accounts

    plan = plan if plan is not None else accounts_plan(conn, months, skip_loaded)
    todo = [(i, label, url) for i, (label, url, done) in enumerate(plan) if not done]
    for label, url, done in plan:
        if done and JOB is not None:
            JOB.skip(label, "already loaded")
    results = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        nxt = pool.submit(download, todo[0][2], DATA_DIR, True) if todo else None
        for k, (i, label, url) in enumerate(todo):
            if JOB is not None:
                JOB.stage(label)
            path = nxt.result()
            # Start fetching the following month in the background (no progress
            # reporting from that thread, to keep this stage's bar meaningful).
            nxt = pool.submit(download, todo[k + 1][2], DATA_DIR, False) if k + 1 < len(todo) else None
            name = path.name
            newest = i == 0
            log(f"Reading {name}")
            r = accounts.run(conn, [path], record_changes=newest, progress=_scaled(0.15))
            conn.commit()
            results.append({"file": name, **{x: v for x, v in r.items() if x != "messages"}})
            log(f"{name}: {r['companies_matched']:,} filings, {r['periods']:,} figures, {r['changes']:,} changes")
            if not keep:  # kept if loading failed, so a re-run does not download it again
                path.unlink(missing_ok=True)
    return results


def fetch_psc(conn, keep: bool = False) -> dict:
    from .importers import psc

    found = links("psc")
    if not found:
        raise RuntimeError("No PSC snapshot found on the Companies House download page")
    newest = found[0][0][:10]
    parts = [url for key, url in found if key.startswith(newest)]
    names = ", ".join(sorted(u.rsplit("/", 1)[-1] for u in parts))
    if conn.execute("select 1 from import_run where kind = 'psc' and filename = %s and finished_at is not null",
                    (names,)).fetchone():
        log(f"Skipping owners: snapshot {newest} is already loaded")
        return {"skipped": names}
    paths = [download(u) for u in sorted(parts)]
    r = psc.run(conn, paths, progress=_scaled(0.15))
    if not keep:  # kept if loading failed, so a re-run does not download them again
        for p in paths:
            p.unlink(missing_ok=True)
    return r


def refresh(conn, accounts_months: int = 1, psc: bool = True, reread_old: bool = False) -> dict:
    """The monthly job: company data, then owners, then accounts (newest month
    first), then scoring, links and map locations. Each part is committed as
    it finishes, so a stop or failure keeps what was already loaded."""
    from . import scoring
    from .ownership import rebuild_links

    # Bulk loads: do not wait for each commit to reach the disk. A power cut
    # could lose the last few seconds, which a re-run restores.
    conn.execute("set synchronous_commit = off")
    out: dict = {}

    def part(label, fn):
        if JOB is not None:
            JOB.stage(label)
        try:
            out[label] = fn()
            conn.commit()
        except Exception as e:
            conn.rollback()
            from .jobs import Cancelled

            if isinstance(e, Cancelled):
                raise
            log(f"{label} failed: {e}")
            out[label] = {"error": str(e)}

    part("Company register", lambda: fetch_company_data(conn))
    # Owners before accounts: one snapshot covers every company, whereas
    # accounts take a file per month.
    if psc:
        part("Owners (PSC)", lambda: fetch_psc(conn))
    try:
        plan = accounts_plan(conn, accounts_months, reread_old=reread_old)
    except Exception as e:
        plan = []
        out["accounts"] = {"error": str(e)}
    if JOB is not None:
        # Show every month as its own step, between owners and scoring.
        names = [st["name"] for st in JOB.stages]
        at = names.index("Scoring") if "Scoring" in names else len(names)
        for label, _, _ in plan:
            if label not in names:
                JOB.stages.insert(at, {"name": label, "status": "waiting", "seconds": None})
                at += 1
    try:
        out["accounts"] = fetch_accounts(conn, plan=plan)
    except Exception as e:
        conn.rollback()
        from .jobs import Cancelled

        if isinstance(e, Cancelled):
            raise
        log(f"Accounts failed: {e}")
        out["accounts"] = {"error": str(e)}
    part("Scoring", lambda: scoring.rescore_all(conn, progress=_loader_progress))
    part("Ownership links", lambda: rebuild_links(conn) or "done")

    def locate():
        from . import geo

        return geo.geocode(conn)

    part("Map locations", locate)
    return out


def run_job(kind: str = "refresh", accounts_months: int = 1, reread_old: bool = False) -> dict:
    """Run refresh() as a tracked job (progress visible on every page)."""
    global JOB
    from . import db
    from .jobs import Cancelled, Job

    JOB = Job(kind, ["Company register", "Owners (PSC)", "Scoring", "Ownership links", "Map locations"])
    try:
        db.migrate()
        with db.conn() as c:
            result = refresh(c, accounts_months=accounts_months, reread_old=reread_old)
        failed = [k for k, v in result.items() if isinstance(v, dict) and v.get("error")]
        JOB.finish(result, status="done", error=("Some parts failed: " + ", ".join(failed)) if failed else None)
        return result
    except Cancelled as e:
        JOB.finish(None, status="cancelled", error=str(e))
        return {"cancelled": True}
    except Exception as e:
        JOB.finish(None, status="failed", error=str(e))
        raise
    finally:
        JOB = None


def scheduler():
    """Run refresh() once a month. Day and hour come from REFRESH_DAY and
    REFRESH_HOUR (defaults: the 6th at 03:00, after Companies House has
    published the month's files)."""
    from . import db

    day = int(os.environ.get("REFRESH_DAY", "6"))
    hour = int(os.environ.get("REFRESH_HOUR", "3"))
    months = int(os.environ.get("REFRESH_ACCOUNTS_MONTHS", "1"))
    log(f"Scheduler started: monthly refresh on day {day} at {hour:02d}:00")
    last = None
    while True:
        now = datetime.now()
        if now.day == day and now.hour == hour and last != (now.year, now.month):
            last = (now.year, now.month)
            log("Monthly refresh starting")
            try:
                result = run_job("scheduled", accounts_months=months)
                log(f"Monthly refresh finished: {result}")
            except Exception as e:
                log(f"Monthly refresh failed: {e}")
        time.sleep(300)
