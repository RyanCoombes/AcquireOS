"""Companies House Streaming API (optional CH_STREAM_KEY), run by the scheduler.

One long-lived connection per stream (companies, filings, officers, owners,
charges, insolvency). For each event:
- a company-profile event updates that company's status for every company,
  so dissolutions, strike-off notices and insolvencies show within minutes
  rather than at the monthly load (recorded as a change, source 'stream');
- an event about a company you are pursuing, or a target already fetched
  from the API, marks it in ch_dirty; the background sync (chsync) re-fetches
  it first and records the detailed changes.

Each stream's position (timepoint) is saved, so a restart carries on from
where it stopped (Companies House keeps a limited history).
"""
from __future__ import annotations

import base64
import json
import os
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import config, db

BASE = "https://stream.companieshouse.gov.uk"
STREAMS = {
    "companies": "/companies",
    "filings": "/filings",
    "officers": "/officers",
    "owners": "/persons-with-significant-control",
    "charges": "/charges",
    "insolvency": "/insolvency-cases",
    "disqualified": "/disqualified-officers",
    "exemptions": "/company-exemptions",
    "owner_statements": "/persons-with-significant-control-statements",
}
_NUM = re.compile(r"/company/([A-Za-z0-9]{8})(?:/|$)")

# Streaming API status (with detail) -> the register's wording, as loaded from the bulk file.
_STATUS = {
    "active": "active", "dissolved": "dissolved", "liquidation": "liquidation", "administration": "in administration",
    "receivership": "receiver action", "voluntary-arrangement": "voluntary arrangement",
    "insolvency-proceedings": "insolvency proceedings", "converted-closed": "converted-closed", "closed": "closed",
    "removed": "removed from register",
}


def enabled() -> bool:
    return bool(config.CH_STREAM_KEY)


def log(msg: str):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [ch-stream] {msg}", flush=True)


def register_status(data: dict) -> str | None:
    """The register's wording for a company-profile event, or None if unknown."""
    st = (data.get("company_status") or "").lower()
    detail = (data.get("company_status_detail") or "").lower()
    if st == "active" and "proposal-to-strike-off" in detail:
        return "active - proposal to strike off"
    return _STATUS.get(st)


def company_number(ev: dict) -> str | None:
    m = _NUM.search(ev.get("resource_uri") or "")
    if m:
        return m.group(1).upper()
    num = (ev.get("data") or {}).get("company_number")
    return num.upper() if isinstance(num, str) and len(num) == 8 else None


def process(conn, batch: list[tuple[str, dict]]) -> dict:
    """Apply a batch of (stream, event). Returns counts."""
    statuses: dict[str, str] = {}
    touched: dict[str, set[str]] = {}
    disq = 0
    for stream, ev in batch:
        if stream == "disqualified":
            # A disqualified officer's record: stored for matching against directors.
            uri = (ev.get("resource_uri") or "").strip("/")
            if "disqualified-officers/" in uri and (ev.get("event") or {}).get("type") != "deleted" and ev.get("data"):
                from . import chextras
                chextras.save_disqualified(conn, uri.split("disqualified-officers/", 1)[1], ev["data"], "stream")
                disq += 1
            continue
        num = company_number(ev)
        if not num:
            continue
        touched.setdefault(num, set()).add(stream)
        if stream == "companies" and (ev.get("event") or {}).get("type") != "deleted":
            st = register_status(ev.get("data") or {})
            if st:
                statuses[num] = st
    out = {"status_changes": 0, "marked": 0, "disqualified": disq}
    if statuses:
        nums, sts = list(statuses), [statuses[n] for n in statuses]
        out["status_changes"] = conn.execute(
            """insert into company_change (company_number, kind, field, old_value, new_value, source)
               select c.company_number, 'status', 'status', c.status, u.st, 'stream'
               from unnest(%s::text[], %s::text[]) as u(num, st) join company c on c.company_number = u.num
               where c.status is distinct from u.st""", (nums, sts)).rowcount
        conn.execute(
            """update company c set status = u.st, status_changed_at = now()
               from unnest(%s::text[], %s::text[]) as u(num, st)
               where c.company_number = u.num and c.status is distinct from u.st""", (nums, sts))
    if touched:
        nums = list(touched)
        kinds = [",".join(sorted(touched[n])) for n in nums]
        out["marked"] = conn.execute(
            """insert into ch_dirty (company_number, kinds)
               select u.num, string_to_array(u.k, ',') from unnest(%s::text[], %s::text[]) as u(num, k)
               where exists (select 1 from user_company uc where uc.company_number = u.num and uc.user_id = 1
                             and uc.status not in ('new', 'passed', 'rejected'))
                  or (exists (select 1 from company_best cb where cb.company_number = u.num)
                      and exists (select 1 from ch_fetch f where f.company_number = u.num))
               on conflict (company_number) do update set last_at = now(),
                 kinds = (select array_agg(distinct x) from unnest(ch_dirty.kinds || excluded.kinds) x)""",
            (nums, kinds)).rowcount
    return out


class Streamer:
    def __init__(self):
        self.q: queue.Queue = queue.Queue(maxsize=20000)
        self.state = {name: {"connected": False, "events": 0, "last_at": None, "error": None, "tp": None}
                      for name in STREAMS}
        self.totals = {"status_changes": 0, "marked": 0, "disqualified": 0, "since": datetime.now(timezone.utc).isoformat()}
        self.lock = threading.Lock()

    # -- reading ------------------------------------------------------------
    def read(self, name: str):
        auth = base64.b64encode(f"{config.CH_STREAM_KEY}:".encode()).decode()
        delay = 5
        while True:
            tp = self.state[name]["tp"]
            url = BASE + STREAMS[name] + (f"?timepoint={tp}" if tp else "")
            req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    self._set(name, connected=True, error=None)
                    log(f"{name}: connected" + (f" from timepoint {tp}" if tp else ""))
                    delay = 5
                    for line in r:
                        line = line.strip()
                        if not line:
                            continue  # heartbeat
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        self.q.put((name, ev))
                raise ConnectionError("stream closed")
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self._set(name, connected=False, error="Companies House rejected the stream key (CH_STREAM_KEY)")
                    time.sleep(3600)
                    continue
                if e.code in (400, 416):  # timepoint too old: start from now
                    self._set(name, connected=False, error="saved position expired; starting from now", tp=None)
                    continue
                self._set(name, connected=False, error=f"HTTP {e.code}")
                delay = max(delay, 60) if e.code == 429 else delay
            except Exception as e:
                self._set(name, connected=False, error=str(e)[:160])
            time.sleep(delay)
            delay = min(delay * 2, 300)

    def _set(self, name, **kw):
        with self.lock:
            self.state[name].update(kw)

    # -- writing ------------------------------------------------------------
    def write(self):
        last_save = 0.0
        while True:
            batch: list[tuple[str, dict]] = []
            deadline = time.time() + 2
            while len(batch) < 2000 and time.time() < deadline:
                try:
                    batch.append(self.q.get(timeout=max(0.05, deadline - time.time())))
                except queue.Empty:
                    break
            try:
                if batch:
                    with db.conn(dedicated=True) as c:
                        got = process(c, batch)
                    with self.lock:
                        for k in ("status_changes", "marked", "disqualified"):
                            self.totals[k] += got[k]
                        now = datetime.now(timezone.utc).isoformat()
                        for name, ev in batch:
                            s = self.state[name]
                            s["events"] += 1
                            s["last_at"] = now
                            tp = (ev.get("event") or {}).get("timepoint")
                            if tp is not None:
                                s["tp"] = max(int(tp), int(s["tp"] or 0))
                if time.time() - last_save > 15:
                    self.save()
                    last_save = time.time()
            except Exception as e:  # keep going; the events are lost but the sync's timed checks catch up
                log(f"write error: {e}")
                time.sleep(10)

    def save(self):
        with self.lock:
            value = {"streams": json.loads(json.dumps(self.state)), **self.totals}
        with db.conn(dedicated=True) as c:
            c.execute(
                """insert into app_setting (key, value, updated_at) values ('ch_stream', %s, now())
                   on conflict (key) do update set value = excluded.value, updated_at = now()""", (json.dumps(value),))

    def load(self):
        """Carry on from the saved positions."""
        try:
            with db.conn(dedicated=True) as c:
                r = c.execute("select value from app_setting where key = 'ch_stream'").fetchone()
            for name, s in ((r or {}).get("value") or {}).get("streams", {}).items():
                if name in self.state and s.get("tp"):
                    self.state[name]["tp"] = s["tp"]
        except Exception:
            pass


def run():
    """Start the stream readers and the writer (threads); returns at once."""
    if not enabled():
        return None
    names = [n.strip() for n in os.environ.get("CH_STREAMS", ",".join(STREAMS)).split(",") if n.strip() in STREAMS]
    s = Streamer()
    s.load()
    threading.Thread(target=s.write, daemon=True, name="ch-stream-writer").start()
    for i, name in enumerate(names):
        threading.Thread(target=lambda n=name, d=i: (time.sleep(d * 2), s.read(n)), daemon=True,
                         name=f"ch-stream-{name}").start()
    log(f"started: {', '.join(names)}")
    return s


def status(conn) -> dict:
    r = conn.execute("select value, updated_at from app_setting where key = 'ch_stream'").fetchone()
    dirty = conn.execute("select count(*) as n from ch_dirty").fetchone()["n"]
    if not r:  # the key is set on the scheduler, so the app only knows it from the saved state
        return {"enabled": enabled(), "live": False, "streams": {}, "waiting": dirty}
    fresh = (datetime.now(timezone.utc) - r["updated_at"]).total_seconds() < 300
    streams = r["value"].get("streams", {})
    return {"enabled": True, "live": fresh and any(s.get("connected") for s in streams.values()),
            "streams": streams, "since": r["value"].get("since"), "status_changes": r["value"].get("status_changes", 0),
            "marked": r["value"].get("marked", 0), "waiting": dirty, "updated_at": r["updated_at"]}


def live(conn) -> bool:
    r = conn.execute("select value, updated_at from app_setting where key = 'ch_stream'").fetchone()
    return bool(r and (datetime.now(timezone.utc) - r["updated_at"]).total_seconds() < 300
                and any(s.get("connected") for s in (r["value"].get("streams") or {}).values()))
