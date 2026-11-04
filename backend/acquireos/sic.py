"""SIC 2007 code descriptions.

A small seed of the codes most relevant to IT, software and data businesses,
plus every division (first two digits). Full descriptions are learnt from
any import that carries them, such as the Companies House bulk file, whose
SIC columns read "62020 - Information technology consultancy activities".
"""
from __future__ import annotations

import re

SEED = {
    "43210": "Electrical installation",
    "46510": "Wholesale of computers, computer peripheral equipment and software",
    "47410": "Retail sale of computers, peripheral units and software in specialised stores",
    "58210": "Publishing of computer games",
    "58290": "Other software publishing",
    "61100": "Wired telecommunications activities",
    "61200": "Wireless telecommunications activities",
    "61300": "Satellite telecommunications activities",
    "61900": "Other telecommunications activities",
    "62011": "Ready-made interactive leisure and entertainment software development",
    "62012": "Business and domestic software development",
    "62020": "Information technology consultancy activities",
    "62030": "Computer facilities management activities",
    "62090": "Other information technology service activities",
    "63110": "Data processing, hosting and related activities",
    "63120": "Web portals",
    "63990": "Other information service activities n.e.c.",
    "64209": "Activities of other holding companies n.e.c.",
    "70100": "Activities of head offices",
    "70210": "Public relations and communications activities",
    "70221": "Financial management",
    "70229": "Management consultancy activities other than financial management",
    "73110": "Advertising agencies",
    "74100": "Specialised design activities",
    "74909": "Other professional, scientific and technical activities n.e.c.",
    "80200": "Security systems service activities",
    "82990": "Other business support service activities n.e.c.",
    "85590": "Other education n.e.c.",
    "95110": "Repair of computers and peripheral equipment",
    "95120": "Repair of communication equipment",
    "99999": "Dormant company",
}

DIVISIONS = {
    "41": "Construction of buildings", "42": "Civil engineering", "43": "Specialised construction activities",
    "45": "Motor trades", "46": "Wholesale trade", "47": "Retail trade",
    "49": "Land transport", "52": "Warehousing and transport support",
    "55": "Accommodation", "56": "Food and beverage services",
    "58": "Publishing activities", "59": "Film, video and music production", "60": "Broadcasting",
    "61": "Telecommunications", "62": "Computer programming, consultancy and related activities",
    "63": "Information service activities", "64": "Financial services", "65": "Insurance and pensions",
    "66": "Activities auxiliary to financial services", "68": "Real estate activities",
    "69": "Legal and accounting activities", "70": "Head offices and management consultancy",
    "71": "Architecture and engineering", "72": "Scientific research and development",
    "73": "Advertising and market research", "74": "Other professional, scientific and technical activities",
    "77": "Rental and leasing", "78": "Employment activities", "79": "Travel agencies and tour operators",
    "80": "Security and investigation", "81": "Services to buildings and landscape",
    "82": "Office administration and business support", "85": "Education", "86": "Human health activities",
    "87": "Residential care", "88": "Social work", "90": "Creative and arts activities",
    "93": "Sports and recreation", "94": "Membership organisations", "95": "Repair of computers and household goods",
    "96": "Other personal services", "99": "Dormant",
}

_PAIR = re.compile(r"\b(\d{4,5})\s*-\s*([^,;|]+)")


def seed(conn):
    with conn.cursor() as cur:
        cur.executemany(
            "insert into sic_code (code, description, source) values (%s, %s, 'seed') on conflict do nothing",
            list(SEED.items()),
        )


def learn(conn, texts) -> int:
    """Store descriptions found in "62020 - Description" text."""
    found = {}
    for t in texts:
        for code, desc in _PAIR.findall(t or ""):
            found[code.zfill(5)] = desc.strip()
    if found:
        with conn.cursor() as cur:
            cur.executemany(
                """insert into sic_code (code, description, source) values (%s, %s, 'companies house')
                   on conflict (code) do update set description = excluded.description, source = excluded.source""",
                list(found.items()),
            )
    return len(found)


def describe(code: str, known: dict[str, str]) -> str:
    return known.get(code) or (f"{DIVISIONS[code[:2]]} (division {code[:2]})" if code[:2] in DIVISIONS else "")
