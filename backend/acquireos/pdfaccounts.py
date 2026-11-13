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
VERSION = 7  # 6: keeps the full text and each figure's line, for checking; 7: staff written as a sentence or a table by role

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
_NUM = re.compile(r"\(?-?£?\s?\d[\d,]*(?:\.\d+)?\)?|(?<![\w.])-(?![\w.])")
_NOTE = re.compile(r"^\d{1,2}$")  # a plain one- or two-digit number: usually a note reference
# The staff note, in its many wordings: "average (monthly) number of employees",
# "... of persons, including directors, employed", "average headcount", "number of
# staff employed", "the company employed an average of 84 people".
_EMP_LABEL = (r"(?:average (?:monthly |weekly )?(?:head ?count|number of (?:full[- ]time equivalent )?"
              r"(?:persons|people|employees|staff|members of staff)(?:[^.0-9]{0,60}?\bemployed)?)"
              r"|employed an average of)")
_EMPLOYEES = re.compile(_EMP_LABEL + r"[^0-9]{0,200}?((?:\d{1,5}\b[^0-9]{0,24}){1,6})")
# "was 84 (2024 - 50)", "84 (2024: 50)": the prior year's figure in brackets after it.
_EMP_PRIOR = re.compile(r"^\D{0,40}?(\d{1,5})[^\d(]{0,20}\(\s*(?:19|20)\d\d\s*[-–—:]?\s*(\d{1,5}|nil)\s*\)")


class _Anchor:
    """A stand-in for a regex match at a position (the staff label with no number near it)."""
    def __init__(self, pos: int):
        self.pos = pos

    def start(self, g: int = 0) -> int:
        return self.pos

    def group(self, g: int = 0) -> str:
        return ""


def _staff_from(numbers: str) -> int | None:
    """The staff count after the label: column headings like "2025 2024"
    come first in many layouts, so skip year-like numbers (1990-2035)."""
    for tok in re.findall(r"\d{1,5}", numbers):
        v = int(tok)
        if 1990 <= v <= 2035:
            continue
        return v if 0 < v < 100_000 else None
    return None
_THOUSANDS = re.compile(r"£\s?'?\s?000|£000s?|£k\b")
_MILLIONS = re.compile(r"£\s?'?\s?m\b|£\s?millions?\b|£\s?'?\s?000,?000\b|\bin millions\b", re.I)


def _scale_of(text: str) -> float | None:
    """The money scale a page (or document) states: millions, thousands, or None."""
    if _MILLIONS.search(text):
        return 1_000_000.0
    if _THOUSANDS.search(text):
        return 1000.0
    return None


def _value(tok: str) -> float | None:
    t = tok.strip()
    if t == "-":
        return 0.0
    neg = t.startswith("(") or t.startswith("-")
    core = re.sub(r"[^\d.,]", "", t)
    # "4.97" (£m accounts) is a decimal; "1.234" is a thousands separator OCR read as a dot.
    m = re.fullmatch(r"([\d,]*\d)\.(\d{1,2})", core)
    if m:
        v = float(m.group(1).replace(",", "") + "." + m.group(2))
    else:
        digits = re.sub(r"[^\d]", "", core)
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
    # Scale per page: statements in £000 or £m and notes in £ are common in one filing.
    doc_scale = _scale_of(text) or 1.0
    found: dict[str, list[float | None]] = {}
    src: dict[str, str] = {}  # the line (as read) each figure came from
    raw_lines = text.splitlines()
    lines = [_clean(" ".join(raw.replace("’", "'").split())) for raw in raw_lines]
    page_scale: list[float] = []
    if any(l.startswith("[[page ") for l in raw_lines):
        cur, buf, starts = doc_scale, [], []
        pages: list[tuple[int, int]] = []
        start = 0
        for i, l in enumerate(raw_lines + ["[[page end]]"]):
            if l.startswith("[[page ") and i > start:
                pages.append((start, i)); start = i
        for a, b in pages:
            sc = _scale_of("\n".join(raw_lines[a:b]))
            page_scale += [sc if sc is not None else 1.0] * (b - a)
    else:
        page_scale = [doc_scale] * len(raw_lines)
    scale = doc_scale
    for i, line in enumerate(lines):
        scale = page_scale[i] if i < len(page_scale) else doc_scale
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
            src[field] = " ".join(raw_lines[i].split())
            break
    flat = " ".join(text.lower().split())
    flat = re.sub(r"([a-z])- ([a-z])", r"\1\2", flat)  # words split across lines by OCR: "em- ployees"
    m = _EMPLOYEES.search(flat)
    employees = _staff_from(m.group(1)) if m else None
    if m is None:
        lab = re.search(_EMP_LABEL, flat)
        if lab:  # label with a table below it: only the "total" row can be trusted
            m = re.match(r"(.)", flat[lab.start():])  # a stand-in match anchored at the label
            m = _Anchor(lab.start())
    employees_prior = None
    if m:
        pm = _EMP_PRIOR.search(flat[m.start(1) - 1 if m.start(1) else 0:])
        if pm and int(pm.group(1)) == employees:
            employees_prior = 0 if pm.group(2) == "nil" else int(pm.group(2))
        # A staff table split by role: take its total, not the first row.
        tm = re.search(r"\btotal\b[^0-9]{0,30}(\d{1,5})(?:[^0-9]{1,24}(\d{1,5}))?", flat[m.start(0): m.start(0) + 500])
        if tm and (employees is None or int(tm.group(1)) > employees) and not (1990 <= int(tm.group(1)) <= 2035):
            employees = int(tm.group(1))
            if tm.group(2) and not (1990 <= int(tm.group(2)) <= 2035):
                employees_prior = int(tm.group(2))
    # "No employees… (2020: Nil)", "the average number of employees was nil": none, not 2020.
    if employees is None and re.search(r"(average (?:monthly )?number of (?:persons employed|employees|staff)[^.]{0,80}?\b(?:nil|none)\b"
                                       r"|\bno employees\b|\bhad no (?:employees|staff)\b)", flat):
        employees = 0
    from .importers.accounts import implausible_staff

    if employees and implausible_staff(employees, (found.get("turnover") or [None])[0]):
        employees = None
    if employees is not None and m:
        src["employees"] = m.group(0)

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
    if "net_assets" in found and "net_assets" not in src and "equity" in src:
        src["net_assets"] = src["equity"]
    # A staff table by role with an unlabelled total row ("Management 4 4 / Staff 34 29 / 38 33"):
    # the total is the numbers-only row after the roles that the roles add up to.
    if m is not None:
        lines = [" ".join(x.split()) for x in text.lower().splitlines()]
        start = next((i for i, x in enumerate(lines) if re.search(_EMP_LABEL, re.sub(r"([a-z])- ([a-z])", r"\1\2", x))), None)
        if start is not None:
            roles, total = [], None
            for x in lines[start + 1: start + 14]:
                nums = [int(n) for n in re.findall(r"\b\d{1,5}\b", x) if not 1990 <= int(n) <= 2035]
                words = re.sub(r"[\d\s.,:()-]", "", x)
                if nums and len(words) >= 3 and "total" not in x:
                    roles.append(nums)
                elif nums and not words and len(roles) >= 2:
                    total = nums
                    break
            if total and roles:
                cur = sum(r[0] for r in roles)
                if abs(total[0] - cur) <= max(1, cur // 20):
                    employees = total[0]
                    prv = [r[1] for r in roles if len(r) > 1]
                    if len(total) > 1 and len(prv) == len(roles) and abs(total[1] - sum(prv)) <= max(1, sum(prv) // 20):
                        employees_prior = total[1]
    if employees_prior is not None and implausible_staff(employees_prior, (found.get("turnover") or [None, None])[1]):
        employees_prior = None
    return {"figures": found, "employees": employees, "employees_prior": employees_prior, "dropped": dropped, "thousands": doc_scale == 1000.0,
            "lines": {k: v for k, v in src.items() if k in found or k == "employees"}}


def pdf_text(pdf: bytes, ocr_pages: int = 20) -> tuple[str, str]:
    """(text, method): the text layer if there is one, else OCR."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join(f"[[page {i + 1}]]\n" + (pg.extract_text() or "") for i, pg in enumerate(reader.pages[:60]))
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
                out.append(f"[[page {int(re.sub(r'\D', '', name) or 0)}]]\n" + (r.stdout or ""))
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
    result = {"status": "failed", "method": None, "figures": {}, "note": None, "sample": None, "full_text": None, "lines": None}
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
                result["full_text"] = text[:300_000]
                if not text.strip():
                    result["note"] = "no text could be read" + ("" if ocr_available() else " (OCR is not installed)")
                else:
                    ex = extract(text)
                    result["lines"] = ex.get("lines") or None
                    mu = date.fromisoformat(made_up)
                    cur = {k: v[0] for k, v in ex["figures"].items() if v[0] is not None}
                    if ex["employees"] is not None:
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
                        if ex.get("employees_prior") is not None:
                            prior["employees"] = ex["employees_prior"]
                        pe = prior_period_end(conn, num, mu)
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
        """insert into pdf_read (company_number, made_up, status, method, figures, note, sample, version, full_text, lines)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (company_number, made_up) do update set status = excluded.status, method = excluded.method,
             figures = excluded.figures, note = excluded.note, sample = excluded.sample, version = excluded.version,
             full_text = excluded.full_text, lines = excluded.lines, tries = pdf_read.tries + 1, read_at = now()""",
        (num, made_up, result["status"], result["method"], json.dumps(result["figures"]), result["note"],
         result["sample"], VERSION, result["full_text"], json.dumps(result["lines"]) if result["lines"] else None))
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
                  and coalesce(fp.source, '') not in ('pdf:text', 'pdf:ocr'))  -- figures saved by you or Claude count
  and not exists (select 1 from pdf_read r where r.company_number = aa.company_number and r.made_up = aa.made_up
                  and (r.status in ('done', 'closed') or r.version >= %(version)s or r.tries >= 3))
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
           where r.status in ('failed', 'nothing_found') order by r.read_at desc limit %s""", (limit,)).fetchall()


def retry(conn, company_number: str | None = None) -> int:
    """Try years that couldn't be read again (one company, or all)."""
    return conn.execute(
        "delete from pdf_read where status in ('failed', 'nothing_found')" + (" and company_number = %s" if company_number else ""),
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
                               count(*) filter (where status = 'done' and method = 'claude') as by_claude,
                               count(*) filter (where status = 'closed') as closed,
                               count(*) filter (where status = 'nothing_found') as nothing_found,
                               count(*) filter (where status = 'failed') as failed,
                               max(read_at) as last_at from pdf_read""").fetchone()
    from . import chsync

    return {**r, "queue": queue_size(conn), "ocr": ocr_available(), "suspicious": suspicious_count(conn),
            "paused": bool(chsync.get_setting(conn, "pdf_paused", False))}


# Figures the reader produced (not ones saved by you or Claude, nor read as data).
_READER = "(fp.source like 'pdf:%%' and fp.source <> 'pdf:claude')"


def redo(conn) -> dict:
    """Clear every figure the PDF reader produced and queue those years to be
    read again by the current reader. Saved figures (yours, Claude's) and
    accounts read as data are kept."""
    gone = conn.execute(f"""delete from financial_period fp where {_READER}
                            returning company_number, period_end""").fetchall()
    conn.execute("""delete from figure_check k using (select unnest(%s::text[]) as n, unnest(%s::date[]) as p) g
                    where k.company_number = g.n and k.period_end = g.p""",
                 ([r["company_number"] for r in gone], [r["period_end"] for r in gone]))
    years = conn.execute("""delete from pdf_read where status in ('failed', 'nothing_found')
                            or (status = 'done' and method in ('text', 'ocr'))""").rowcount
    nums = sorted({r["company_number"] for r in gone})
    # Rescore with rescore_later(nums) once this is committed.
    return {"figures_cleared": len(gone), "companies": len(nums), "years_queued": years, "_nums": nums}


def rescore_later(nums: list[str]) -> None:
    if nums:
        import threading

        threading.Thread(target=_rescore, args=(nums,), daemon=True, name="pdf-redo").start()


def _rescore(nums: list[str]) -> None:
    from . import db, scoring
    from .importers.companies import refresh_estimates

    with db.conn(dedicated=True) as c:
        c.execute("create temp table if not exists redo_touched (company_number text)")
        c.execute("delete from redo_touched")
        c.execute("insert into redo_touched select unnest(%s::text[])", (nums,))
        refresh_estimates(c, from_table="redo_touched")
        scoring.refresh_latest(c, from_table="redo_touched")
        c.commit()
        for n in nums:
            scoring.rescore(c, company_number=n)
            c.commit()


SUSPICIOUS_SQL = f"""
with mine as (select distinct company_number from financial_period fp where {_READER}),
f as (
    select fp.*, lag(fp.turnover) over w as prev_t, lead(fp.turnover) over w as next_t, lag(fp.employees) over w as prev_e
    from financial_period fp join mine using (company_number)
    where not fp.period_inferred
    window w as (partition by fp.company_number order by fp.period_end)
),
flagged as (
    select f.company_number, f.period_end, f.source, f.turnover, f.gross_profit, f.operating_profit,
           f.net_assets, f.cash, f.employees,
           array_remove(array[
             case when f.turnover > 0 and f.prev_t > 0 and (f.turnover > 10 * f.prev_t or 10 * f.turnover < f.prev_t)
                  then 'turnover ' || round(f.turnover / f.prev_t, 1) || '× the year before' end,
             case when f.turnover > 0 and f.next_t > 0 and (f.next_t > 10 * f.turnover or 10 * f.next_t < f.turnover)
                  then 'turnover ' || round(f.turnover / f.next_t, 1) || '× the year after' end,
             case when f.turnover > 0 and f.gross_profit > f.turnover then 'gross profit bigger than turnover' end,
             case when f.turnover > 0 and abs(f.operating_profit) > f.turnover then 'operating profit bigger than turnover' end,
             case when f.turnover >= 100000 and (abs(f.gross_profit) between 0.01 and 99 or abs(f.operating_profit) between 0.01 and 99
                       or abs(f.net_assets) between 0.01 and 99 or abs(f.cash) between 0.01 and 99)
                  then 'a figure under £100 beside turnover of ' || case when f.turnover >= 1000000
                       then '£' || round(f.turnover / 1000000, 2) || 'm' else '£' || round(f.turnover / 1000) || 'k' end end,
             case when f.employees >= 20 and f.prev_e > 0 and f.employees > 10 * f.prev_e
                  then 'staff ' || f.employees || ', ten times the year before (' || f.prev_e || ')' end,
             case when f.turnover > 0 and f.employees > 0 and f.turnover / f.employees > 5000000
                  then 'over £5m turnover per employee' end,
             case when f.turnover > 0 and f.employees >= 5 and f.turnover / f.employees < 5000
                  then 'under £5k turnover per employee' end
           ], null) as why
    from f
    where f.source like 'pdf:%%' and f.source <> 'pdf:claude'
      and not exists (select 1 from figure_check k where k.company_number = f.company_number and k.period_end = f.period_end)
)
select x.*, c.name from flagged x join company c using (company_number)
where cardinality(x.why) > 0
"""


def suspicious(conn, limit: int = 500) -> list[dict]:
    """Years read from a PDF whose figures look wrong, worth checking against the PDF."""
    return conn.execute(SUSPICIOUS_SQL + " order by cardinality(x.why) desc, x.turnover desc nulls last limit %(limit)s",
                        {"limit": limit}).fetchall()


def suspicious_count(conn) -> int:
    return conn.execute("select count(*) as n from (" + SUSPICIOUS_SQL + ") s", {}).fetchone()["n"]


def mark_checked(conn, company_number: str, period_end: str) -> None:
    conn.execute("insert into figure_check (company_number, period_end) values (%s, %s) on conflict do nothing",
                 (company_number.strip().upper(), period_end))


# --- Checking a reading against the PDF (Data page) ---------------------------

CHECK_FIELDS = ["turnover", "gross_profit", "operating_profit", "profit_loss", "employees", "net_assets", "cash",
                "debtors", "fixed_assets", "current_assets", "net_current_assets", "total_assets_less_cl",
                "creditors_within", "creditors_after", "stock", "staff_costs", "director_pay", "dividends",
                "depreciation", "amortisation", "interest_payable", "tax", "bank_loans"]


def years_to_check(conn, show: str = "check", q: str | None = None, limit: int = 200) -> list[dict]:
    """PDF-read years: those worth checking (figures that look wrong), or all of
    them, newest read first. Optionally filtered by company name or number."""
    if show == "check":
        rows = [dict(r, made_up=r["period_end"], checked=False) for r in suspicious(conn, 2000)]
        if q:
            ql = q.lower().strip()
            rows = [r for r in rows if ql in r["name"].lower() or ql == r["company_number"].lower()]
        return rows[:limit]
    where, params = "", {"limit": limit}
    if q:
        where = "and (c.name ilike %(q)s or c.company_number = upper(%(qn)s))"
        params.update(q=f"%{q.strip()}%", qn=q.strip())
    return conn.execute(f"""
        select r.company_number, c.name, r.made_up, r.made_up as period_end, r.method, r.read_at,
               exists (select 1 from figure_check k where k.company_number = r.company_number
                       and abs(k.period_end - r.made_up) <= 45) as checked,
               '{{}}'::text[] as why
        from pdf_read r join company c using (company_number)
        where r.status = 'done' and r.method in ('text', 'ocr') {where}
        order by r.read_at desc limit %(limit)s""", params).fetchall()


def _reading_for(conn, num: str, period_end: str):
    """The PDF reading that supplied a year: its own accounts, or the next
    year's (whose prior-year column it was)."""
    r = conn.execute("""select *, 'current' as col from pdf_read where company_number = %(n)s and status = 'done'
                        and abs(made_up - %(p)s::date) <= 45 order by read_at desc limit 1""",
                     {"n": num, "p": period_end}).fetchone()
    if r:
        return r
    return conn.execute("""select *, 'prior' as col from pdf_read where company_number = %(n)s and status = 'done'
                           and abs(made_up - (%(p)s::date + interval '1 year')::date) <= 45
                           order by read_at desc limit 1""", {"n": num, "p": period_end}).fetchone()


def check_detail(conn, company_number: str, period_end: str) -> dict | None:
    num = company_number.strip().upper()
    c = conn.execute("select name from company where company_number = %s", (num,)).fetchone()
    if not c:
        return None
    fp = conn.execute("""select * from financial_period where company_number = %s and not period_inferred
                         and abs(period_end - %s::date) <= 45 order by abs(period_end - %s::date) limit 1""",
                      (num, period_end, period_end)).fetchone()
    r = _reading_for(conn, num, str(fp["period_end"]) if fp else period_end)
    why = next((x["why"] for x in suspicious(conn, 5000) if x["company_number"] == num
                and fp and x["period_end"] == fp["period_end"]), [])
    return {
        "company_number": num, "name": c["name"], "period_end": str(fp["period_end"]) if fp else period_end,
        "source": fp["source"] if fp else None,
        "figures": {k: (float(fp[k]) if fp and fp.get(k) is not None else None) for k in CHECK_FIELDS},
        "made_up": str(r["made_up"]) if r else None, "column": r["col"] if r else None,
        "method": r["method"] if r else None, "note": r["note"] if r else None, "read_at": r["read_at"] if r else None,
        "text": (r["full_text"] or r["sample"]) if r else None, "full": bool(r and r["full_text"]),
        "lines": (r["lines"] or {}) if r else {}, "why": why,
        "checked": bool(fp and conn.execute("select 1 from figure_check where company_number = %s and period_end = %s",
                                            (num, fp["period_end"])).fetchone()),
    }


def pdf_bytes(conn, company_number: str, made_up: str) -> bytes | None:
    from . import chapi

    f = conn.execute("""select detail from filing where company_number = %s and type = 'AA'
                        and detail->>'made_up_date' = %s order by filed_on desc limit 1""",
                     (company_number.strip().upper(), made_up)).fetchone()
    link = (f or {}).get("detail", {}).get("document") if f else None
    return chapi._document(link, limit=25_000_000) if link else None


def correct(conn, company_number: str, period_end: str, values: dict) -> dict:
    """Your corrections to a PDF-read year: saved as yours (a later re-read never
    replaces them), a blank clears a wrong figure, and the year is marked checked."""
    from .importers.accounts import _upsert

    num = company_number.strip().upper()
    pe = date.fromisoformat(period_end)
    old = conn.execute("select * from financial_period where company_number = %s and period_end = %s", (num, pe)).fetchone() or {}
    keep = {k: v for k, v in values.items() if k in CHECK_FIELDS and v is not None}
    clear = [k for k, v in values.items() if k in CHECK_FIELDS and v is None and old.get(k) is not None]
    if keep:
        _upsert(conn, num, pe, keep, "manual", balance_date=pe)
    if clear:
        conn.execute(f"update financial_period set {', '.join(f'{k} = null' for k in clear)}, source = 'manual' "
                     "where company_number = %s and period_end = %s", (num, pe))
    changes = [f"{k.replace('_', ' ')}: {old.get(k) if old.get(k) is not None else 'blank'} → {keep.get(k, 'blank')}"
               for k in [*keep, *clear] if (float(old[k]) if old.get(k) is not None else None) != keep.get(k)]
    if changes:
        conn.execute("""insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
                        values (%s, 'other', %s, 'manual', 'Checked against the PDF', 'me', 'high')""",
                     (num, f"Corrected the {pe:%b %Y} accounts figures read from the PDF: " + "; ".join(changes)))
    mark_checked(conn, num, str(pe))
    return {"changed": changes}


def prior_period_end(conn, num: str, made_up: date) -> date:
    """The year end of the comparison column in accounts made up to made_up: the
    company's previous accounts, which aren't always 12 months earlier (a year
    end moved, e.g. a 15-month period to 30 September 2025 compares with 30 June
    2024). From its filed accounts or the years already held; 12 months earlier
    only when neither is known."""
    r = conn.execute(
        """select max(d) as d from (
             select (detail->>'made_up_date')::date as d from filing
              where company_number = %(n)s and type = 'AA' and detail->>'made_up_date' ~ '^\\d{4}-\\d{2}-\\d{2}$'
             union all
             select period_end from financial_period
              where company_number = %(n)s and not period_inferred
                and (source_balance_date - period_end) <= 45) x
           where d >= %(mu)s - interval '24 months' and d < %(mu)s - 45  -- over 45 days: not the same year (52/53-week years)""",
        {"n": num, "mu": made_up}).fetchone()
    if r and r["d"]:
        return r["d"]
    try:
        return made_up.replace(year=made_up.year - 1)
    except ValueError:  # 29 February
        return made_up.replace(year=made_up.year - 1, day=28)


def fix_false_prior_years(conn) -> dict:
    """Remove years that exist only because a PDF's comparison column was dated
    12 months back when the year end had moved: a comparison-only row with a
    real year (from its own accounts) 6 weeks to 6 months away. Figures the real
    year is missing are moved across first; saves by you or Claude are kept."""
    rows = conn.execute(
        """select f.company_number, f.period_end, r.period_end as real_end
           from financial_period f
           join lateral (select r.period_end from financial_period r
                         where r.company_number = f.company_number and not r.period_inferred
                           and r.period_end <> f.period_end and abs(r.period_end - f.period_end) between 46 and 200
                           and (r.source_balance_date - r.period_end) <= 45
                         order by abs(r.period_end - f.period_end) limit 1) r on true
           where (f.period_inferred
                  or (f.source in ('pdf:text', 'pdf:ocr') and f.source_balance_date - f.period_end > 45))""").fetchall()
    cols = [r["column_name"] for r in conn.execute(
        """select column_name from information_schema.columns where table_name = 'financial_period'
           and column_name not in ('company_number', 'period_end', 'period_inferred', 'source', 'source_balance_date')
           and data_type in ('numeric', 'integer', 'bigint', 'double precision', 'real')""")]
    for r in rows:
        if cols:
            sets = ", ".join(f"{c} = coalesce(t.{c}, x.{c})" for c in cols)
            conn.execute(f"""update financial_period t set {sets} from financial_period x
                             where t.company_number = %(n)s and t.period_end = %(real)s
                               and x.company_number = %(n)s and x.period_end = %(false)s""",
                         {"n": r["company_number"], "real": r["real_end"], "false": r["period_end"]})
        conn.execute("delete from financial_period where company_number = %s and period_end = %s",
                     (r["company_number"], r["period_end"]))
    nums = sorted({r["company_number"] for r in rows})
    if nums:
        from . import scoring
        from .importers.companies import refresh_estimates
        conn.execute("drop table if exists prior_fix")
        conn.execute("create temp table prior_fix (company_number text)")
        conn.execute("insert into prior_fix select unnest(%s::text[])", (nums,))
        refresh_estimates(conn, from_table="prior_fix")
        scoring.refresh_latest(conn, from_table="prior_fix")
        for n in nums:
            scoring.rescore(conn, company_number=n)
    return {"removed": len(rows), "companies": len(nums)}


def mark_read_by_claude(conn, company_number: str, period_end) -> int:
    """A year Claude read and saved: the PDF reading it replaces is done."""
    return conn.execute("""update pdf_read set status = 'done', method = 'claude', note = 'Read and saved by Claude', read_at = now()
                           where company_number = %s and abs(made_up - %s::date) <= 45 and status <> 'done'""",
                        (company_number.strip().upper(), str(period_end))).rowcount


def close(conn, company_number: str, made_up: str, reason: str) -> int:
    """Checked and nothing to read (e.g. dormant, no profit and loss, illegible): off the list for good."""
    return conn.execute("""update pdf_read set status = 'closed', note = %s, read_at = now()
                           where company_number = %s and made_up = %s::date and status <> 'done'""",
                        (f"Closed: {reason.strip()[:300]}", company_number.strip().upper(), made_up)).rowcount
