"""Read CSV and Excel files into rows, and guess which column is which."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path


def read_rows(path: Path, sheet: str | None = None) -> tuple[list[str], list[dict]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(path, sheet)
    return _read_csv(path)


def list_sheets(path: Path) -> list[str]:
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        return []
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _read_csv(path: Path) -> tuple[list[str], list[dict]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return [], []
    headers = _unique_headers(rows[0])
    out = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue
        out.append({h: (r[i] if i < len(r) else None) for i, h in enumerate(headers)})
    return headers, out


def _read_xlsx(path: Path, sheet: str | None) -> tuple[list[str], list[dict]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else _best_sheet(wb)
        it = ws.iter_rows(values_only=True)
        header_row = None
        # Skip title rows above the real header: use the first row with
        # at least three non-empty cells.
        for row in it:
            if row and sum(1 for v in row if v not in (None, "")) >= 3:
                header_row = row
                break
        if header_row is None:
            return [], []
        headers = _unique_headers(["" if v is None else str(v) for v in header_row])
        out = []
        for row in it:
            if not row or all(v in (None, "") for v in row):
                continue
            out.append({h: (row[i] if i < len(row) else None) for i, h in enumerate(headers)})
        return headers, out
    finally:
        wb.close()


def _best_sheet(wb):
    """Pick the sheet that looks most like a company list."""
    best, best_score = wb.worksheets[0], -1
    for ws in wb.worksheets:
        score = 0
        for row in ws.iter_rows(min_row=1, max_row=5, values_only=True):
            for v in row or ():
                if v and re.search(r"company.?(number|no)|crn", str(v), re.I):
                    score += 10
        if score > best_score:
            best, best_score = ws, score
    return best


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(raw):
        h = (h or "").strip() or f"column_{i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        out.append(h)
    return out


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", h.lower()).strip("_")


def detect(headers: list[str], aliases: dict[str, list[str]]) -> dict[str, str | None]:
    """Map each field to the first header matching one of its aliases.

    An alias starting with "~" matches any header containing it; others
    must match the whole (normalised) header. Aliases are tried in order
    and each header is used at most once.
    """
    normed = {h: norm_header(h) for h in headers}
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for field, names in aliases.items():
        choice = None
        for name in names:
            partial = name.startswith("~")
            key = name.lstrip("~")
            for h, n in normed.items():
                if h in used:
                    continue
                if (partial and key in n) or (not partial and n == key):
                    choice = h
                    break
            if choice:
                break
        mapping[field] = choice
        if choice:
            used.add(choice)
    return mapping
