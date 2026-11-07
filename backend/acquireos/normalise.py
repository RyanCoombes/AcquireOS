"""Cleaning helpers for Companies House data as it arrives from CSVs and Excel."""
from __future__ import annotations

import re
from datetime import date, datetime

POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")

# Addresses that many unrelated companies use. A company registered at one of
# these tells you nothing about where it really operates.
KNOWN_SHARED_ADDRESSES = {
    "CF14 8LH": ("ch_default", "Companies House default address (Cardiff)"),
    "N1 7GU": ("formation_agent", "20-22 Wenlock Road, a formation-agent address"),
    "WC2H 9JQ": ("formation_agent", "71-75 Shelton Street, a formation-agent address"),
    "EC1V 2NX": ("formation_agent", "City Road, a formation-agent address"),
}
ADDRESS_FLAG_LABELS = {
    "ch_default": "Companies House default address",
    "formation_agent": "Formation-agent address",
    "mass_address": "Shared by many companies",
}
# A plain address shared by more companies than this is treated as an
# accountant's or agent's office rather than a trading address.
MASS_ADDRESS_THRESHOLD = 15


def company_number(value) -> str | None:
    """Return the 8-character Companies House number.

    Excel strips leading zeros (2511854 instead of 02511854), so numeric
    values are padded. Prefixed numbers (SC, NI, OC...) keep their prefix.
    """
    if value is None:
        return None
    s = str(value).strip().upper().replace(" ", "")
    if not s or s in {"NAN", "NONE"}:
        return None
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.isdigit():
        return s.zfill(8)
    m = re.fullmatch(r"([A-Z]{1,2})(\d+)", s)
    if m:
        prefix, digits = m.groups()
        return prefix + digits.zfill(8 - len(prefix))
    return s


def text(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def number(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("£", "")
    if not s or s.lower() in {"nan", "none", "-", "n/a"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        n = float(s)
    except ValueError:
        return None
    return -n if neg else n


def integer(value) -> int | None:
    n = number(value)
    return None if n is None else int(round(n))


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    return None


def sic_codes(value) -> list[str]:
    if value is None:
        return []
    found = re.findall(r"\b\d{4,5}\b", str(value))
    seen, out = set(), []
    for code in found:
        code = code.zfill(5)
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def postcode(address: str | None) -> str | None:
    if not address:
        return None
    matches = POSTCODE_RE.findall(address.upper())
    if not matches:
        return None
    outward, inward = matches[-1]
    return f"{outward} {inward}"


def address_key(address: str | None) -> str | None:
    """A loose key so the same address written two ways still matches."""
    if not address:
        return None
    s = address.upper()
    s = re.sub(r"\b(UNITED KINGDOM|UK|ENGLAND|WALES|SCOTLAND|GREAT BRITAIN)\b", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(s.split()) or None


def known_address_flag(pc: str | None) -> tuple[str, str] | None:
    if not pc:
        return None
    return KNOWN_SHARED_ADDRESSES.get(pc)


def name_key(name: str) -> str:
    s = name.upper()
    s = re.sub(r"\b(MR|MRS|MS|MISS|DR|PROF|SIR|DAME|LORD|LADY)\b\.?", " ", s)
    s = re.sub(r"[^A-Z ]+", " ", s)
    return " ".join(s.split())


def company_name_key(name: str) -> str:
    s = name.upper().replace("&", " AND ")
    s = re.sub(r"\b(LIMITED|LTD|PLC|LLP|HOLDINGS?|GROUP|COMPANY|CO)\b\.?", " ", s)
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return " ".join(s.split())


def yes(value) -> bool:
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


# Postcode areas fully in each nation. A few areas straddle a border (SY,
# CH, LD, TD, HR, NP) and are assigned to where most of the area lies.
WALES_AREAS = {"CF", "SA", "NP", "LL", "LD"}
SCOTLAND_AREAS = {"AB", "DD", "DG", "EH", "FK", "G", "HS", "IV", "KA", "KW", "KY", "ML", "PA", "PH", "TD", "ZE"}
NI_AREAS = {"BT"}


def postcode_area(pc: str | None) -> str | None:
    if not pc:
        return None
    m = re.match(r"([A-Z]{1,2})\d", pc.strip().upper())
    return m.group(1) if m else None


def region_for(pc: str | None) -> str | None:
    area = postcode_area(pc)
    if not area:
        return None
    if area in WALES_AREAS:
        return "Wales"
    # Welsh districts in the mostly-English SY and CH areas (Newtown, Welshpool,
    # Aberystwyth; Deeside, Flint, Mold, Holywell). Same rule as ao_region in SQL.
    if re.match(r"^(CH[5-8]|SY(1[5-9]|2[0-5]))(\s|$)", pc.strip().upper()):
        return "Wales"
    if area in SCOTLAND_AREAS:
        return "Scotland"
    if area in NI_AREAS:
        return "Northern Ireland"
    return "England"
