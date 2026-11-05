"""Import your own judgement (notes, ratings, decisions) from a workbook.

Notes are append-only and de-duplicated by content, so importing the same
file twice adds nothing. Status and rating are only set where the app has
no value yet: anything you have already changed in the app wins.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import config
from .. import normalise as n
from .tables import detect, norm_header, read_rows

from ..stages import LABELS as STATUS_LABELS, STATUSES  # noqa: E402,F401

ALIASES = {
    "company_number": ["company_number", "companynumber", "company_no", "crn", "number", "~company_number"],
    "status": ["my_status", "decision", "pipeline_status", "pipeline", "~decision", "~verdict", "outcome"],
    "rating": ["rating", "my_rating", "stars", "~rating"],
    "next_action": ["next_action", "next_step", "~next_action", "~next_step"],
}
NOTE_HINTS = ("note", "assess", "comment", "review", "thought", "why", "reason", "verdict", "research", "summary")

# Words in a free-text decision column, mapped to app statuses.
STATUS_WORDS = [
    (("reject", "no go", "nogo", "exclude", "not a fit", "drop", "kill"), "rejected"),
    (("pass", "skip", "park"), "passed"),
    (("heads of terms", "hot", "exclusiv"), "heads"),
    (("due diligence", "diligence"), "diligence"),
    (("offer", "loi"), "offer"),
    (("nda",), "nda"),
    (("in talks", "meeting"), "in_talks"),
    (("contacted", "letter sent", "emailed", "called"), "contacted"),
    (("approach", "contact", "shortlist", "yes", "go"), "approach"),
    (("research", "check", "maybe", "unclear", "investigate"), "researching"),
    (("watch", "monitor", "later"), "watching"),
]


def map_status(value) -> str | None:
    s = (n.text(value) or "").lower()
    if not s:
        return None
    if s.replace(" ", "_") in STATUSES:
        return s.replace(" ", "_")
    for words, status in STATUS_WORDS:
        if any(w in s for w in words):
            return status
    return None


def note_columns(headers: list[str], mapping: dict) -> list[str]:
    used = {h for h in mapping.values() if h}
    return [h for h in headers if h not in used and any(k in norm_header(h) for k in NOTE_HINTS)]


def preview(path: Path, sheet: str | None = None) -> dict:
    headers, rows = read_rows(path, sheet)
    mapping = detect(headers, ALIASES)
    notes = note_columns(headers, mapping)
    return {
        "headers": headers,
        "mapping": {**mapping, "notes": notes},
        "row_count": len(rows),
        "sample": rows[:5],
        "fields": list(ALIASES.keys()) + ["notes"],
        "problems": [] if mapping.get("company_number") else ["No company number column found."],
    }


def run(conn, path: Path, mapping: dict | None = None, sheet: str | None = None,
        source: str | None = None, user_id: int = config.DEFAULT_USER_ID) -> dict:
    headers, rows = read_rows(path, sheet)
    if mapping is None:
        mapping = detect(headers, ALIASES)
        mapping["notes"] = note_columns(headers, mapping)
    if not mapping.get("company_number"):
        raise ValueError("No company number column found. Map one before importing.")
    source = source or path.name
    file_nums = list({n.company_number(r.get(mapping["company_number"])) for r in rows} - {None})
    known = {r["company_number"] for r in conn.execute(
        "select company_number from company where company_number = any(%s)", (file_nums,))}
    run_id = conn.execute(
        "insert into import_run (kind, filename, rows_in) values ('notes', %s, %s) returning id",
        (source, len(rows)),
    ).fetchone()["id"]

    ok = skipped = notes_added = 0
    messages: list[str] = []
    unmapped_status: dict[str, int] = {}
    for i, row in enumerate(rows, start=2):
        num = n.company_number(row.get(mapping["company_number"]))
        if not num or num not in known:
            skipped += 1
            if num and len(messages) < 50:
                messages.append(f"Row {i}: {num} is not in the company list yet. Import company data first.")
            continue
        raw_status = row.get(mapping["status"]) if mapping.get("status") else None
        status = map_status(raw_status)
        if raw_status and not status:
            key = str(raw_status).strip()[:40]
            unmapped_status[key] = unmapped_status.get(key, 0) + 1
        rating = n.integer(row.get(mapping["rating"])) if mapping.get("rating") else None
        if rating is not None and not 1 <= rating <= 5:
            rating = None
        next_action = n.text(row.get(mapping["next_action"])) if mapping.get("next_action") else None
        tags = [f"imported: {str(raw_status).strip()[:40]}"] if raw_status and not status else []

        conn.execute(
            """insert into user_company (user_id, company_number, status, rating, next_action, tags)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (user_id, company_number) do update set
                 status = case when user_company.status = 'new' then excluded.status else user_company.status end,
                 rating = coalesce(user_company.rating, excluded.rating),
                 next_action = coalesce(user_company.next_action, excluded.next_action),
                 tags = (select array(select distinct unnest(user_company.tags || excluded.tags)))""",
            (user_id, num, status or "new", rating, next_action, tags),
        )
        for col in mapping.get("notes") or []:
            body = n.text(row.get(col))
            if not body:
                continue
            text = f"{col}: {body}"
            h = hashlib.sha256(text.encode()).hexdigest()
            res = conn.execute(
                """insert into user_note (user_id, company_number, body, source, content_hash)
                   values (%s, %s, %s, %s, %s) on conflict do nothing returning id""",
                (user_id, num, text, f"import:{source}", h),
            ).fetchone()
            if res:
                notes_added += 1
        ok += 1

    if unmapped_status:
        messages.append(
            "Decision values kept as tags because they did not match a status: "
            + ", ".join(f"“{k}” ({v})" for k, v in sorted(unmapped_status.items(), key=lambda x: -x[1])[:10])
        )
    conn.execute(
        "update import_run set rows_ok=%s, rows_skipped=%s, messages=%s, finished_at=now() where id=%s",
        (ok, skipped, json.dumps(messages), run_id),
    )
    return {"run_id": run_id, "rows_in": len(rows), "rows_ok": ok, "rows_skipped": skipped,
            "notes_added": notes_added, "messages": messages}
