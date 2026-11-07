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

FIELDS = ("turnover", "gross_profit", "operating_profit", "profit_loss", "net_assets", "cash", "debtors")

# Labels at the start of a line (lower-cased, punctuation simplified).
LABELS: list[tuple[str, re.Pattern]] = [
    ("turnover", re.compile(r"^(turnover|revenue|sales)\b(?!.*\bcost\b)")),
    ("gross_profit", re.compile(r"^gross (profit|loss|\(loss\)\s*/\s*profit|profit\s*/\s*\(loss\))")),
    ("operating_profit", re.compile(r"^(operating (profit|loss|\(loss\)\s*/\s*profit|profit\s*/\s*\(loss\))|"
                                    r"(profit|loss) from operations|profit\s*/\s*\(loss\) from operations)")),
    ("profit_loss", re.compile(r"^((profit|loss|\(loss\)\s*/\s*profit|profit\s*/\s*\(loss\)) for the (financial )?(year|period)|"
                               r"(profit|loss|\(loss\)\s*/\s*profit|profit\s*/\s*\(loss\)) after tax(ation)?)")),
    ("net_assets", re.compile(r"^(net (assets|liabilities|\(liabilities\)\s*/\s*assets|assets\s*/\s*\(liabilities\)))\b")),
    ("equity", re.compile(r"^(total equity|shareholders'?\s*funds|total shareholders'?\s*funds)\b")),
    ("cash", re.compile(r"^(cash at bank( and in hand)?|cash and cash equivalents|cash in hand)\b")),
    ("debtors", re.compile(r"^(debtors|trade and other receivables)\b")),
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


def extract(text: str) -> dict:
    """{field: [current, prior]} from accounts text, plus employees and the
    checks applied. Values in pounds."""
    scale = 1000.0 if _THOUSANDS.search(text) else 1.0
    found: dict[str, list[float | None]] = {}
    for raw in text.splitlines():
        line = " ".join(raw.replace("’", "'").split())
        low = line.lower().lstrip("•*- ").strip()
        if not low:
            continue
        for field, rx in LABELS:
            if field in found or not rx.search(low):
                continue
            # Numbers after the label; a small leading number is a note reference.
            toks = [m.group(0).strip() for m in _NUM.finditer(line[rx.search(low).end():])]
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
    t = (found.get("turnover") or [None])[0]
    for f, lim in (("gross_profit", 1.0), ("operating_profit", 1.0), ("profit_loss", 1.5)):
        v = (found.get(f) or [None])[0]
        if v is not None and t and abs(v) > abs(t) * lim:
            dropped.append(f"{f.replace('_', ' ')} (larger than turnover)")
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


def ocr(pdf: bytes, pages: int = 20) -> str:
    if not ocr_available():
        return ""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.pdf")
        with open(src, "wb") as f:
            f.write(pdf)
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(pages), "-png", src, os.path.join(d, "p")],
                       check=False, timeout=600, preexec_fn=_nice, capture_output=True)
        out = []
        for name in sorted(n for n in os.listdir(d) if n.endswith(".png")):
            r = subprocess.run(["tesseract", os.path.join(d, name), "stdout", "--psm", "6"],
                               check=False, timeout=180, preexec_fn=_nice, capture_output=True, text=True)
            out.append(r.stdout or "")
        return "\n".join(out)


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
    result = {"status": "failed", "method": None, "figures": {}, "note": None}
    try:
        if not link:
            result["note"] = "no document link for these accounts"
        else:
            pdf = chapi._document(link, limit=25_000_000)
            if not pdf:
                result["note"] = "Companies House did not return the document"
            else:
                text, method = pdf_text(pdf)
                result["method"] = method
                if not text.strip():
                    result["note"] = "no text could be read" + ("" if ocr_available() else " (OCR is not installed)")
                else:
                    ex = extract(text)
                    mu = date.fromisoformat(made_up)
                    cur = {k: v[0] for k, v in ex["figures"].items() if v[0] is not None}
                    if ex["employees"]:
                        cur["employees"] = ex["employees"]
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
                        if prior and not has_prior:
                            _upsert(conn, num, pe, prior, f"pdf:{method}", balance_date=mu)
                        result.update(status="done", figures=cur)
                    else:
                        result["status"] = "nothing_found"
                    if ex["dropped"]:
                        result["note"] = "left out: " + "; ".join(ex["dropped"])
    except Exception as e:
        result["note"] = str(e)[:200]
    import json

    conn.execute(
        """insert into pdf_read (company_number, made_up, status, method, figures, note)
           values (%s, %s, %s, %s, %s, %s)
           on conflict (company_number, made_up) do update set status = excluded.status, method = excluded.method,
             figures = excluded.figures, note = excluded.note, read_at = now()""",
        (num, made_up, result["status"], result["method"], json.dumps(result["figures"]), result["note"]))
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


QUEUE_SQL = """
-- Newest year first across all companies (every company's latest PDF-only
-- accounts before anyone's second-latest), back at most 5 years; within a
-- year, your pipeline first, then the best-scoring targets.
with todo as (
    select f.company_number, d.value::date as made_up,
           row_number() over (partition by f.company_number order by d.value::date desc) as nth
    from ch_fetch f cross join lateral jsonb_array_elements_text(f.accounts_pdf) d
    where d.value::date > current_date - interval '5 years 6 months'
      and not exists (select 1 from pdf_read r where r.company_number = f.company_number and r.made_up = d.value::date)
)
select t.company_number, t.made_up from todo t
order by t.nth,
         exists (select 1 from user_company uc where uc.company_number = t.company_number and uc.user_id = 1
                 and uc.status not in ('new', 'passed', 'rejected')) desc,
         (select max(score) from company_best cb where cb.company_number = t.company_number) desc nulls last,
         t.made_up desc
limit %s"""


def queue_size(conn) -> int:
    return conn.execute(
        """select count(*) as n from ch_fetch f cross join lateral jsonb_array_elements_text(f.accounts_pdf) d
           where d.value::date > current_date - interval '5 years 6 months'
             and not exists (select 1 from pdf_read r where r.company_number = f.company_number
                             and r.made_up = d.value::date)""").fetchone()["n"]


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
                rows = c.execute(QUEUE_SQL, (5,)).fetchall()
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
                               count(*) filter (where status = 'nothing_found') as nothing_found,
                               count(*) filter (where status = 'failed') as failed,
                               max(read_at) as last_at from pdf_read""").fetchone()
    from . import chsync

    return {**r, "queue": queue_size(conn), "ocr": ocr_available(),
            "paused": bool(chsync.get_setting(conn, "pdf_paused", False))}
