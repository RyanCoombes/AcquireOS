"""Acquisition stages, from first look to handover, with a checklist each.

Stage keys are stored in user_company.status. The first six keys predate the
deal stages and are kept so existing data stays valid.
"""
from __future__ import annotations

# (key, label, phase, description, checklist)
STAGES: list[tuple[str, str, str, str, list[str]]] = [
    ("new", "New", "assess", "Not looked at yet", []),
    ("watching", "Watching", "assess", "Interesting; check again later", []),
    ("researching", "Assessing", "assess", "Working out whether it fits", [
        "Accounts reviewed (three or more years)",
        "Website and services checked",
        "Owners and their ages confirmed",
        "Recurring revenue estimated",
        "No field-service or van-based red flags",
        "Rough value and funding check done",
    ]),
    ("approach", "Shortlisted", "assess", "Worth approaching", [
        "Approach angle written",
        "Letter or email drafted",
        "Introduction route checked (accountant, adviser, mutual contact)",
    ]),
    ("contacted", "First contact", "engage", "Letter, call or introduction", [
        "Letter, call or introduction sent",
        "Follow-up date set",
        "Reply received",
    ]),
    ("in_talks", "Getting to know", "engage", "Meetings, no numbers yet", [
        "First meeting held",
        "Owner's goals and timing understood",
        "Owner's role after a sale discussed",
        "Fit confirmed both ways",
    ]),
    ("nda", "NDA and accounts", "engage", "Accounts, clients, who does what", [
        "NDA signed",
        "Management accounts received",
        "Client list and concentration reviewed",
        "Team and key people understood",
    ]),
    ("offer", "Indicative offer", "deal", "Price range and structure, in writing", [
        "Valuation updated with real numbers",
        "Funding route outlined (bank, DBW, vendor loan)",
        "Price range and structure sent in writing",
    ]),
    ("heads", "Heads of terms", "deal", "Exclusivity, often 4 to 8 weeks", [
        "Heads of terms agreed and signed",
        "Exclusivity period agreed",
        "Lawyer and accountant instructed",
        "Lender engaged",
    ]),
    ("diligence", "Due diligence", "deal", "Lender credit process runs alongside", [
        "Financial due diligence",
        "Legal due diligence",
        "Commercial and customer checks",
        "Lender credit approval",
    ]),
    ("spa", "SPA and disclosure", "deal", "Lawyers draft the purchase agreement", [
        "Share purchase agreement drafted",
        "Disclosure letter reviewed",
        "Warranties and indemnities agreed",
        "Completion mechanics agreed",
    ]),
    ("completion", "Completion", "deal", "Funds paid, shares transfer", [
        "Funds drawn and paid",
        "Shares transferred",
        "Companies House filings made",
    ]),
    ("handover", "Handover", "owned", "Owner supports for the agreed period", [
        "Handover plan agreed",
        "Staff and clients told",
        "Owner support period under way",
    ]),
    ("passed", "Passed", "closed", "Not pursuing for now", []),
    ("rejected", "Rejected", "closed", "Not a fit", []),
]

PHASES = [("assess", "Assess"), ("engage", "Engage"), ("deal", "Deal"), ("owned", "Owned"), ("closed", "Closed")]

STATUSES = [s[0] for s in STAGES]
LABELS = {s[0]: s[1] for s in STAGES}
PHASE_OF = {s[0]: s[2] for s in STAGES}
CHECKLISTS = {s[0]: s[4] for s in STAGES}
# "In the pipeline" means given any status except these.
NOT_ACTIVE = ("new", "rejected", "passed")


def as_json():
    return [{"value": k, "label": l, "phase": p, "description": d, "checklist": c} for k, l, p, d, c in STAGES]


def item_key(label: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:60]
