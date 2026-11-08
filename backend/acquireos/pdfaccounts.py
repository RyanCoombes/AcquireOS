"""Read accounts that Companies House holds only as PDF (not in the bulk data).

1. Text: the PDF's own text layer when it has one (most electronically filed
   PDFs do); otherwise OCR with Tesseract (free) on the first pages, at low
   priority so it never starves the rest of the Pi.
2. Figures: labelled lines (Turnover, Operating profit, Net assets, Cash at
   bank...) with the current and prior-year columns, bracketed losses and
   £'000 units.
3. Checks: figures that contradict each other are dropped, not guessed
   (net assets against total equity, profit against turnover, and so on).

Saved figures are marked as read from a PDF (source "pdf:text" or
"pdf:ocr") so they always show as "read automatically: check them".
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date

FIELDS = ("turnover", "gross_profit", "operating_profit", "profit_loss", "net_assets", "cash", "debtors",
          "creditors_within", "creditors_after", "stock")

# Labels at the start of a line (lower-cased, punctuation simplified).
# Bump when reading improves: years that couldn't be read are tried again.
VERSION = 5

_PL = r"(profit|loss|\(loss\)\s*/\s*profit|profit\s*/\s*\(loss\)|\(profit\)\s*/\s*loss|loss\s*/\s*\(profit\))"
LABELS: list[tuple[str, re.Pattern]] = [
    ("turnover", re.compile(r"^(turnover|revenue|sales)\b(?!.*\b(cost|represents|is recognised|comprises)\b)")),
    ("gross_profit", re.compile(rf"^gross {_PL}")),
    ("operating_profit", re.compile(rf"^(operating {_PL}|{_PL} from operations)")),
    ("profit_loss", re.compile(rf"^({_PL} for the (financial )?(year|period)|{_PL} after tax(ation)?|"
                               rf"{_PL} on ordinary activities after tax(ation)?|"
                               r"total comprehensive (income|\(loss\)|loss|income\s*/\s*\(loss\)) for the (financial )?(year|period))")),
    ("net_assets", re.compile(r"^(total )?net (assets|liabilities|\(liabilities\)\s*/\s*assets|assets\s*/\s*\(liabilities\))\b")),
    ("equity", re.compile(r"^(total equity|(total )?capital and reserves|(total )?(shareholders|members)'?\s*(funds|\(deficit\)\s*/\s*funds|funds\s*/\s*\(deficit\)|deficit))\b")),
    ("cash", re.compile(r"^(cash at bank( and in hand)?|cash and cash equivalents|cash in hand|cash)\b(?!\s*flow)")),
    ("debtors", re.compile(r"^(debtors|trade and other receivables)\b")),
    ("creditors_within", re.compile(r"^creditors:?\s*(amounts )?falling due within one year\b")),
    ("creditors_after", re.compile(r"^creditors:?\s*(amounts )?falling due after (more than )?one year\b")),
    ("stock", re.compile(r"^(stocks?|inventories)\b(?!\s*(exchange|market))")),
]
_NUM = re.compile(r"\(?-?£?\s?\d[\d,]*\)?|(?<![\w.])-(?![\w.])")
_NOTE = re.compile(r"^\d{1,2}$")  # a plain one- or two-digit number: usually a note reference
_EMPLOYEES = re.compile(r"average (?:monthly )?number of (?:persons employed|employees|staff|people employed)"
                        r"[^0-9]{0,200}?(\d{1,5})\b")
_THOUSANDS = re.compile(r"£\s?'?\s?000|£000s?|£k\b")


def _value(tok: str) -> float | None:
    t = tok.strip()
    if t == "-":
        return 0.0
    neg = t.startswith("(") or t.startswith("-")
    digits = re.sub(r"[^\d]", "", t)
    if not digits:
        return None
    v = float(digits)
    return -v if neg else v


_NUMLINE = re.compile(r"^[\s£(),.\d-]+$")


def _clean(line: str) -> str:
    """Common OCR slips in figures: £ read as E or €, O for 0, l/I for 1,
    full stops for thousands commas (4.123.456), stray table rules."""
    line = line.replace("|", " ").replace("€", "£")
    line = re.sub(r"(?<![A-Za-z])E(?=\s?\d)", "£", line)
    line = re.sub(r"(?<=\d)[Oo](?=[\d,)])|(?<=[\d,(])[Oo](?=\d)", "0", line)
    line = re.sub(r"(?<=\d)[lI](?=[\d,])|(?<=[\d,(])[lI](?=\d)", "1", line)
    line = re.sub(r"\b(\d{1,3})\.(\d{3})\.(\d{3})\b", r"\1,\2,\3", line)
    line = re.sub(r"\b(\d{1,3})\.(\d{3})\b(?!\.\d)", r"\1,\2", line)
    return line


def extract(text: str) -> dict:
    """{field: [current, prior]} from accounts text, plus employees and the
    checks applied. Values in pounds."""
    scale = 1000.0 if _THOUSANDS.search(text) else 1.0
    found: dict[str, list[float | None]] = {}
    lines = [_clean(" ".join(raw.replace("’", "'").split())) for raw in text.splitlines()]
    for i, line in enumerate(lines):
        low = line.lower().lstrip("•*- ").strip()
        if not low:
            continue
        for field, rx in LABELS:
            if field in found or not rx.search(low):
                continue
            # Numbers after the label; a small leading number is a note reference.
            rest = line[len(line) - len(low):][rx.search(low).end():]
            toks = [m.group(0).strip() for m in _NUM.finditer(rest)]
            toks = [t for t in toks if t and t != "£"]
            if not toks and not re.search(r"[a-z]{3}", rest.lower()):
                # Text taken from a table often puts the figures on the next
                # lines: take up to four lines that are only numbers.
                for nxt in lines[i + 1:i + 5]:
                    if not nxt.strip():
                        continue
                    if not _NUMLINE.match(nxt):
                        break
                    toks += [m.group(0).strip() for m in _NUM.finditer(nxt)]
                    if len([t for t in toks if not _NOTE.match(t)]) >= 2:
                        break
                toks = [t for t in toks if t and t != "£"]
            # A leading note reference ("Turnover 3 4,123,456 3,812,004"): a plain
            # 1-2 digit number followed by two figures, or by one larger figure.
            if len(toks) >= 2 and _NOTE.match(toks[0]) and (
                    len(toks) >= 3 or len(re.sub(r"[^\d]", "", toks[1])) >= 3):
                toks = toks[1:]
            vals = [_value(t) for t in toks]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            cur = vals[0] * scale
            prior = vals[1] * scale if len(vals) > 1 else None
            if field in ("operating_profit", "profit_loss", "gross_profit") and low.startswith("loss") and cur > 0:
                cur, prior = -cur, (-prior if prior and prior > 0 else prior)
            found[field] = [cur, prior]
            break
    m = _EMPLOYEES.search(" ".join(text.lower().split()))
    employees = int(m.group(1)) if m and 0 < int(m.group(1)) < 100_000 else None

    dropped = []
    # Net assets must agree with total equity when both are given.
    if "net_assets" in found and "equity" in found:
        a, b = found["net_assets"][0], found["equity"][0]
        if a is not None and b is not None and abs(a - b) > max(abs(a), abs(b)) * 0.01 + 1:
            dropped.append("net assets (does not match total equity)")
            del found["net_assets"]
            found.pop("equity")  # one of them is misread: use neither
    if "net_assets" not in found and "equity" in found:
        found["net_assets"] = found["equity"]
    found.pop("equity", None)
    # Turnover is never negative, and doesn't jump twentyfold in a year: either
    # column like that is a misread (a note number, a bracketed subtotal).
    if "turnover" in found:
        cur, prior = found["turnover"]
        if cur is not None and cur <= 0:
            dropped.append("turnover (not a positive figure)")
            del found["turnover"]
        elif prior is not None and (prior <= 0 or (cur and (cur / prior > 20 or prior / cur > 20))):
            found["turnover"] = [cur, None]
            dropped.append("prior-year turnover (doesn't fit the current year)")
    t = (found.get("turnover") or [None])[0]
    for f, lim in (("gross_profit", 1.0), ("operating_profit", 1.0), ("profit_loss", 1.5)):
        v = (found.get(f) or [None])[0]
        if v is not None and t and abs(v) > abs(t) * lim:
            dropped.append(f"{f.replace('_', ' ')} (larger than turnover)")
            del found[f]
    for f in ("creditors_within", "creditors_after", "stock"):  # sizes: shown in brackets on balance sheets
        if f in found:
            found[f] = [abs(v) if v is not None else None for v in found[f]]
    # A tiny figure beside a real turnover is a note number or a misread (e.g. "8"
    # gross profit on £34m): drop it rather than save it.
    if t and t >= 100_000:
        for f in list(found):
            if f != "turnover" and found[f][0] is not None and 0 < abs(found[f][0]) < 100:
                dropped.append(f"{f.replace('_', ' ')} (too small to be right)")
                del found[f]
    for f in list(found):
        if any(v is not None and abs(v) > 1e11 for v in found[f]):
            dropped.append(f"{f.replace('_', ' ')} (implausible)")
            del found[f]
    return {"figures": found, "employees": employees, "dropped": dropped, "thousands": scale == 1000.0}


def pdf_text(pdf: bytes, ocr_pages: int = 20) -> tuple[str, str]:
    """(text, method): the text layer if there is one, else OCR."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages[:60])
    except Exception:
        text = ""
    if len(re.sub(r"[^A-Za-z0-9]", "", text)) >= 400 and re.search(r"\d{1,3},\d{3}", text):
        return text, "text"
    return ocr(pdf, ocr_pages), "ocr"


def ocr_available() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _nice():
    try:
        os.nice(15)  # OCR is heavy: let everything else on the Pi go first
    except OSError:
        pass


# Tesseract on a Raspberry Pi: one thread (its OpenMP threads fight each other
# and everything else on a busy Pi, which is what made pages time out), no
# search for white-on-black text (accounts don't have any; it doubles the work).
_TESS_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}
_TESS_ARGS = ["--psm", "6", "-c", "tessedit_do_invert=0"]
PAGE_TIMEOUT = 300


def _enough(text: str) -> bool:
    """Stop reading more pages once the main figures are in."""
    f = extract(text)["figures"]
    return "net_assets" in f and len(f) >= 3


def ocr(pdf: bytes, pages: int = 20) -> str:
    """OCR page by page, newest first in the order they appear; a page that
    takes too long is skipped (and noted) rather than failing the whole year;
    stops early once the balance sheet and two more figures have been read."""
    if not ocr_available():
        return ""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.pdf")
        with open(src, "wb") as f:
            f.write(pdf)
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(pages), "-png", src, os.path.join(d, "p")],
                       check=False, timeout=600, preexec_fn=_nice, capture_output=True)
        out, skipped = [], []
        names = sorted((n for n in os.listdir(d) if n.endswith(".png")), key=lambda n: int(re.sub(r"\D", "", n) or 0))
        for name in names:
            try:
                r = subprocess.run(["tesseract", os.path.join(d, name), "stdout", *_TESS_ARGS], env=_TESS_ENV,
                                   check=False, timeout=PAGE_TIMEOUT, preexec_fn=_nice, capture_output=True, text=True)
                out.append(r.stdout or "")
            except subprocess.TimeoutExpired:
                skipped.append(re.sub(r"\D", "", name).lstrip("0") or "?")
                continue
            if _enough("\n".join(out)):
                break
        text = "\n".join(out)
        if skipped:
            text += f"\n[OCR skipped page(s) {', '.join(skipped)}: took longer than {PAGE_TIMEOUT // 60} minutes]"
        return text


def _sample(text: str) -> str:
    """The lines that look like the accounts (labels with figures), for
    checking by eye why a year couldn't be read."""
    keep = [l for l in (" ".join(x.split()) for x in text.splitlines())
            if l and (re.search(r"\d[\d,]{2,}", l) or re.search(r"(?i)balance sheet|profit and loss|turnover|net assets|equity|reserves", l))]
    return "\n".join(keep)[:6000]


def read_and_save(conn, company_number: str, made_up: str) -> dict:
    """Fetch one PDF-only set of accounts, read it, save what passes the checks
    and record the outcome in pdf_read."""
    from . import chapi
    from .importers.accounts import _upsert

    num = company_number.strip().upper()
    f = conn.execute(
        """select transaction_id, detail from filing where company_number = %s and type = 'AA'
           and detail->>'made_up_date' = %s order by filed_on desc limit 1""", (num, made_up)).fetchone()
    link = (f or {}).get("detail", {}).get("document") if f else None
    result = {"status": "failed", "method": None, "figures": {}, "note": None, "sample": None}
    try:
        if not link:
            result["note"] = "no document link for these accounts"
        else:
            data_vals = {}
            if "application/xhtml+xml" in chapi._doc_formats(link):
                # Filed as data after all (a bulk month that didn't load): read it exactly.
                from .importers.accounts import parse
                raw = chapi._document(link, limit=20_000_000, accept="application/xhtml+xml")
                data_vals = parse(raw) if raw else {}
            if data_vals:
                for pe, vals in data_vals.items():
                    _upsert(conn, num, pe, vals, f"api:{f['transaction_id']}", balance_date=date.fromisoformat(made_up))
                result.update(status="done", method="data", figures={str(k): "data" for k in data_vals})
                pdf = None
            else:
                pdf = chapi._document(link, limit=25_000_000)
            if result["status"] == "done":
                pass
            elif not pdf:
                result["note"] = "Companies House did not return the document"
            else:
                text, method = pdf_text(pdf)
                result["method"] = method
                result["sample"] = _sample(text)
                if not text.strip():
                    result["note"] = "no text could be read" + ("" if ocr_available() else " (OCR is not installed)")
                else:
                    ex = extract(text)
                    mu = date.fromisoformat(made_up)
                    cur = {k: v[0] for k, v in ex["figures"].items() if v[0] is not None}
                    if ex["employees"]:
                        cur["employees"] = ex["employees"]
                    # Only fill gaps: figures already held for the year (from its data
                    # accounts, or saved by you or Claude) are never replaced by a reading.
                    def held(pe):
                        r = conn.execute("""select * from financial_period where company_number = %s and not period_inferred
                                            and abs(period_end - %s) <= 45 order by abs(period_end - %s) limit 1""",
                                         (num, pe, pe)).fetchone()
                        return {k for k, v in (r or {}).items() if v is not None}
                    have_now = held(mu)
                    kept = [k for k in cur if k in have_now]
                    cur = {k: v for k, v in cur.items() if k not in have_now}
                    if kept:
                        result["note"] = f"already held, not replaced: {', '.join(k.replace('_', ' ') for k in kept)}"
                    if cur:
                        _upsert(conn, num, mu, cur, f"pdf:{method}", balance_date=mu)
                        prior = {k: v[1] for k, v in ex["figures"].items() if v[1] is not None}
                        try:
                            pe = mu.replace(year=mu.year - 1)
                        except ValueError:  # 29 February
                            pe = mu.replace(year=mu.year - 1, day=28)
                        has_prior = conn.execute(
                            """select 1 from financial_period where company_number = %s and not period_inferred
                               and abs(period_end - %s) <= 45""", (num, pe)).fetchone()
                        prior = {k: v for k, v in prior.items() if k not in held(pe)}
                        if prior:
                            _upsert(conn, num, pe, prior, f"pdf:{method}", balance_date=mu)
                        result.update(status="done", figures=cur)
                    elif kept:
                        result.update(status="done", figures={})
                    else:
                        result["status"] = "nothing_found"
                        sk = re.search(r"\[OCR skipped page\(s\) [^\]]+\]", text)
                        if sk:
                            result["note"] = sk.group(0).strip("[]")
                    if ex["dropped"]:
                        result["note"] = "left out: " + "; ".join(ex["dropped"])
    except Exception as e:
        result["note"] = str(e)[:200]
    import json

    conn.execute(
        """insert into pdf_read (company_number, made_up, status, method, figures, note, sample, version)
           values (%s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (company_number, made_up) do update set status = excluded.status, method = excluded.method,
             figures = excluded.figures, note = excluded.note, sample = excluded.sample, version = excluded.version,
             tries = pdf_read.tries + 1, read_at = now()""",
        (num, made_up, result["status"], result["method"], json.dumps(result["figures"]), result["note"],
         result["sample"], VERSION))
    if result["status"] == "done":
        from . import scoring
        from .importers.companies import refresh_estimates

        conn.execute("create temp table if not exists api_touched (company_number text)")
        conn.execute("delete from api_touched")
        conn.execute("insert into api_touched values (%s)", (num,))
        refresh_estimates(conn, from_table="api_touched")
        scoring.refresh_latest(conn, [num])
        scoring.rescore(conn, company_number=num)
    return result


# Years to read: accounts filings within ten years (from each company's
# filing history, fetched by the sync or on opening) with no figures held,
# not dormant, and not read yet (or read by an older version and not found).
TODO_SQL = """
with aa as (
    select distinct on (fl.company_number, (fl.detail->>'made_up_date')::date)
           fl.company_number, (fl.detail->>'made_up_date')::date as made_up
    from filing fl
    where fl.type = 'AA' and fl.detail ? 'document' and fl.detail->>'made_up_date' ~ '^\\d{4}-\\d{2}-\\d{2}$'
      and coalesce(fl.description, '') not like '%%dormant%%'
      /*only*/
    union
    select f.company_number, d.value::date
    from ch_fetch f cross join lateral jsonb_array_elements_text(f.accounts_pdf) d
    where d.value ~ '^\\d{4}-\\d{2}-\\d{2}$' /*only_f*/
)
select aa.company_number, aa.made_up,
       row_number() over (partition by aa.company_number order by aa.made_up desc) as nth
from aa
where aa.made_up > current_date - interval '10 years 6 months'
  and exists (select 1 from filing fl where fl.company_number = aa.company_number and fl.type = 'AA'
              and fl.detail->>'made_up_date' = aa.made_up::text and fl.detail ? 'document')
  and not exists (select 1 from financial_period fp where fp.company_number = aa.company_number
                  and not fp.period_inferred and abs(fp.period_end - aa.made_up) <= 45
                  and coalesce(fp.source, '') not like 'pdf:%%')
  and not exists (select 1 from pdf_read r where r.company_number = aa.company_number and r.made_up = aa.made_up
                  and (r.status = 'done' or r.version >= %(version)s or r.tries >= 3))
"""

QUEUE_SQL = """
-- Newest year first across all companies (every company's latest missing
-- accounts before anyone's second-latest), back at most 10 years; within a
-- year, your pipeline first, then the best-scoring targets.
with todo as (""" + TODO_SQL + """)
select t.company_number, t.made_up from todo t
order by t.nth,
         exists (select 1 from user_company uc where uc.company_number = t.company_number and uc.user_id = 1
                 and uc.status not in ('new', 'passed', 'rejected')) desc,
         (select max(score) from company_best cb where cb.company_number = t.company_number) desc nulls last,
         t.made_up desc
limit %(limit)s"""


def todo_for(conn, company_number: str) -> list[str]:
    """One company's years waiting to be read, newest first."""
    q = TODO_SQL.replace("/*only*/", "and fl.company_number = %(num)s").replace("/*only_f*/", "and f.company_number = %(num)s")
    return [str(r["made_up"]) for r in conn.execute(q + " order by made_up desc",
                                                   {"num": company_number, "version": VERSION})]


def queue(conn, limit: int = 5) -> list[dict]:
    return conn.execute(QUEUE_SQL, {"limit": limit, "version": VERSION}).fetchall()


def queue_size(conn) -> int:
    return conn.execute("select count(*) as n from (" + TODO_SQL + ") t",
                        {"version": VERSION}).fetchone()["n"]


def failures(conn, limit: int = 200) -> list[dict]:
    """Years that couldn't be read, newest first, with why and what was read."""
    return conn.execute(
        """select r.company_number, c.name, r.made_up, r.status, r.method, r.note, r.read_at, r.tries,
                  left(r.sample, 1500) as sample
           from pdf_read r join company c using (company_number)
           where r.status <> 'done' order by r.read_at desc limit %s""", (limit,)).fetchall()


def retry(conn, company_number: str | None = None) -> int:
    """Try years that couldn't be read again (one company, or all)."""
    return conn.execute(
        "delete from pdf_read where status <> 'done'" + (" and company_number = %s" if company_number else ""),
        (company_number,) if company_number else ()).rowcount


def read_company(company_number: str) -> None:
    """Read one company's waiting years now (used by Refresh on the company page)."""
    from . import db

    with db.conn(dedicated=True) as c:
        for mu in todo_for(c, company_number):
            read_and_save(c, company_number, mu)
            c.commit()


def run_forever():
    """Background reader, run by the scheduler: PDF-only accounts found by the
    Companies House sync, your pipeline first, then the best targets. Waits
    while a data load or scoring runs, or when paused on the Data page."""
    import time
    from datetime import datetime

    from . import chapi, chsync, db

    def log(msg):
        print(f"{datetime.now():%Y-%m-%d %H:%M:%S} [pdf-accounts] {msg}", flush=True)

    log(f"started (OCR {'available' if ocr_available() else 'NOT installed: text-layer PDFs only'})")
    while True:
        try:
            if not chapi.enabled():
                time.sleep(600)
                continue
            with db.conn(dedicated=True) as c:
                if c.execute("select to_regclass('pdf_read') as t").fetchone()["t"] is None or chsync.busy(c) \
                        or chsync.get_setting(c, "pdf_paused", False):
                    time.sleep(300)
                    continue
                rows = queue(c, 5)
                if not rows:
                    time.sleep(900)
                    continue
                for r in rows:
                    res = read_and_save(c, r["company_number"], str(r["made_up"]))
                    c.commit()
                    log(f"{r['company_number']} {r['made_up']}: {res['status']} ({res['method']}){' · ' + res['note'] if res['note'] else ''}")
        except Exception as e:
            log(f"error: {e}")
            time.sleep(300)


def status(conn) -> dict:
    r = conn.execute("""select count(*) filter (where status = 'done') as done,
                               count(*) filter (where status = 'done' and method = 'ocr') as by_ocr,
                               count(*) filter (where status = 'done' and method = 'data') as by_data,
                               count(*) filter (where status = 'nothing_found') as nothing_found,
                               count(*) filter (where status = 'failed') as failed,
                               max(read_at) as last_at from pdf_read""").fetchone()
    from . import chsync

    return {**r, "queue": queue_size(conn), "ocr": ocr_available(),
            "paused": bool(chsync.get_setting(conn, "pdf_paused", False))}
