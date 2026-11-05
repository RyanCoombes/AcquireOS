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


def log(msg: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] {msg}", file=sys.stderr, flush=True)


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


def download(url: str, dest_dir: Path = DATA_DIR) -> Path:
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
                with open(tmp, "wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                tmp.rename(dest)
                return dest
        except Exception as e:
            wait = 2 ** (attempt + 2)
            log(f"Download failed ({e}); retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Could not download {url}")


def fetch_company_data(conn, keep: bool = False) -> dict:
    found = links("company")
    if not found:
        raise RuntimeError("No company data file found on the Companies House download page")
    from .importers import register

    path = download(found[0][1])
    try:
        return register.load(conn, path, full=True, progress=log)
    finally:
        if not keep:
            path.unlink(missing_ok=True)


def fetch_accounts(conn, months: int = 1, keep: bool = False, skip_loaded: bool = True) -> list[dict]:
    """Load the newest `months` monthly accounts files, OLDEST FIRST.

    Oldest first means each company's figures build up in date order, and
    every figure also records which filing it came from, so an older filing
    can never overwrite a newer one. Changes (new accounts, staff) are only
    recorded for the newest month, so back-filling history does not flood
    the Changes page."""
    from .importers import accounts

    loaded = {r["filename"] for r in conn.execute("select filename from import_run where kind = 'accounts'")}
    chosen = links("accounts")[:months]            # newest first
    chosen = list(reversed(chosen))                # process oldest first
    results = []
    for i, (_, url) in enumerate(chosen):
        name = url.rsplit("/", 1)[-1]
        if skip_loaded and name in loaded:
            log(f"Skipping {name}: already loaded")
            continue
        newest = i == len(chosen) - 1
        path = download(url)
        try:
            log(f"Reading accounts in {name} ({i + 1} of {len(chosen)})")
            r = accounts.run(conn, [path], record_changes=newest, progress=log)
            conn.commit()
            results.append({"file": name, **{k: v for k, v in r.items() if k != "messages"}})
            log(f"{name}: {r['companies_matched']:,} filings, {r['changes']:,} changes")
        finally:
            if not keep:
                path.unlink(missing_ok=True)
    return results


def fetch_psc(conn, keep: bool = False) -> dict:
    from .importers import psc

    found = links("psc")
    if not found:
        raise RuntimeError("No PSC snapshot found on the Companies House download page")
    newest = found[0][0][:10]
    parts = [url for key, url in found if key.startswith(newest)]
    paths = [download(u) for u in sorted(parts)]
    try:
        return psc.run(conn, paths, progress=log)
    finally:
        if not keep:
            for p in paths:
                p.unlink(missing_ok=True)


def refresh(conn, accounts_months: int = 1, psc: bool = True) -> dict:
    """The monthly job: company data, then accounts, then owners, then rescore."""
    from . import scoring
    from .ownership import rebuild_links

    out: dict = {}
    for label, fn in [
        ("company_data", lambda: fetch_company_data(conn)),
        ("accounts", lambda: fetch_accounts(conn, months=accounts_months)),
        ("psc", (lambda: fetch_psc(conn)) if psc else None),
    ]:
        if fn is None:
            continue
        try:
            out[label] = fn()
            conn.commit()
        except Exception as e:  # keep going: one product failing should not block the others
            conn.rollback()
            log(f"{label} failed: {e}")
            out[label] = {"error": str(e)}
    log("Scoring companies")
    scoring.rescore(conn)
    conn.commit()
    log("Rebuilding ownership links for companies in your buy box")
    rebuild_links(conn)
    conn.commit()
    try:
        from . import geo

        out["map_locations"] = geo.geocode(conn)
        conn.commit()
    except Exception as e:
        log(f"Map location lookup failed: {e}")
    return out


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
                db.migrate()
                with db.conn() as c:
                    result = refresh(c, accounts_months=months)
                log(f"Monthly refresh finished: {result}")
            except Exception as e:
                log(f"Monthly refresh failed: {e}")
        time.sleep(300)
