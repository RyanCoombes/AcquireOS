"""Finding a company's website without search engines or paid services.

1. A research brief: every name the company might trade under (current and
   previous names, its parent and subsidiaries), its registered address and
   its owners, plus ready-made search queries. Claude uses this with its own
   web search, since a subsidiary or trading name is often what the website
   is under.
2. A checker: try likely domains from those names, fetch each home page, and
   accept one only if the page (or its contact, about, privacy or terms page)
   shows the company number or registered postcode. UK companies must show
   their registered number on their website, so that check is a strong one.
"""
from __future__ import annotations

import html as htmlmod
import re
import socket
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; AcquireOS/0.3; website check for a UK company)"
_SUFFIX = re.compile(r"\b(LIMITED|LTD|PLC|LLP|L\.L\.P|CYF|CCC|COMPANY|CO|THE|UK|U\.K|GB|HOLDINGS?|GROUP|SERVICES|SOLUTIONS)\b\.?", re.I)
TLDS = (".co.uk", ".com", ".uk", ".net")


def name_stems(name: str) -> list[str]:
    """Domain stems for a company name: joined and hyphenated, with and
    without generic words (SOLUTIONS, GROUP...), most likely first."""
    base = re.sub(r"&", " and ", name or "", flags=re.I)
    words_all = [w for w in re.sub(r"[^a-z0-9 ]+", " ", base.lower()).split() if w not in ("limited", "ltd", "plc", "llp")]
    words_core = [w for w in re.sub(r"[^a-z0-9 ]+", " ", _SUFFIX.sub(" ", base).lower()).split()]
    stems: list[str] = []
    for words in (words_core, words_all):
        if not words:
            continue
        for s in ("".join(words), "-".join(words)):
            if 3 <= len(s) <= 40 and s not in stems:
                stems.append(s)
        if len(words) > 2:  # "abc it services" -> "abcit"
            s = "".join(words[:2])
            if len(s) >= 4 and s not in stems:
                stems.append(s)
    return stems


def candidates(names: list[str], limit: int = 16) -> list[str]:
    out: list[str] = []
    for n in names:
        for stem in name_stems(n):
            for tld in TLDS:
                d = stem + tld
                if d not in out:
                    out.append(d)
    return out[:limit]


def _resolves(domain: str) -> bool:
    try:
        socket.setdefaulttimeout(4)
        socket.getaddrinfo(domain, 443)
        return True
    except OSError:
        return False


def _fetch(url: str, limit: int = 600_000) -> tuple[str, str] | None:
    """(final url, text) or None."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return None
            return r.geturl(), r.read(limit).decode("utf-8", errors="replace")
    except Exception:
        return None


def _text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", html))


def evidence(text: str, company_number: str, postcode: str | None, names: list[str]) -> tuple[str | None, str]:
    """(confidence, what was found) for one page's text."""
    t = " ".join(text.split())
    num = company_number.upper()
    digits = num.lstrip("0") if num.isdigit() else num
    num_re = re.compile(r"(?<![0-9])0*" + re.escape(digits) + r"(?![0-9])") if num.isdigit() else re.compile(re.escape(num), re.I)
    if num_re.search(t):
        return "high", f"company number {num} is on the site"
    if postcode and re.search(re.escape(postcode).replace(r"\ ", r"\s*"), t, re.I):
        return "medium", f"registered postcode {postcode} is on the site"
    for n in names:
        core = " ".join(_SUFFIX.sub(" ", n).split())
        if len(core) >= 4 and re.search(r"\b" + re.escape(core) + r"\b", t, re.I):
            return "low", f"the name “{core}” appears, but not the company number or postcode"
    return None, ""


_PC_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b")


def addresses(text: str) -> list[dict]:
    """UK postcodes on a page, each with the address text just before it
    (offices listed on a contact or about page). [{postcode, address}]"""
    t = " ".join(text.split())
    out, seen = [], set()
    for m in _PC_RE.finditer(t):
        pc = f"{m.group(1)} {m.group(2)}"
        if pc in seen:
            continue
        seen.add(pc)
        before = t[max(0, m.start() - 110):m.start()]
        # Keep the end of the text before the postcode: the street and town.
        before = re.split(r"(?:\.\s|\||:|©|Tel\b|Phone\b|Email\b|Address\b)", before)[-1]
        parts = [p.strip(" ,") for p in before.split(",") if p.strip(" ,")]
        addr = ", ".join(parts[-4:])
        out.append({"postcode": pc, "address": f"{addr}, {pc}" if addr else pc})
    return out[:8]


def check(url: str, company_number: str, postcode: str | None, names: list[str]) -> dict:
    """Fetch a site's home page (and its contact/about/legal pages if needed)
    and say how sure we are it belongs to the company."""
    if not re.match(r"^https?://", url):
        url = "https://" + url.strip().lstrip("/")
    got = _fetch(url) or (_fetch(url.replace("https://", "http://", 1)) if url.startswith("https://") else None)
    if not got:
        return {"url": url, "reachable": False, "confidence": None, "evidence": "site did not answer"}
    final, html = got
    conf, why = evidence(_text(html), company_number, postcode, names)
    page = final
    found = [{**a, "page": final} for a in addresses(_text(html))]
    links = re.findall(r'href="([^"#]+)"', html, re.I)
    host = urllib.parse.urlparse(final).netloc
    contact = [urllib.parse.urljoin(final, h) for h in links if re.search(r"(contact|locations?|offices?|find-us)", h, re.I)]
    extra = [urllib.parse.urljoin(final, h) for h in links
             if re.search(r"(contact|about|privacy|terms|legal|cookie|imprint|locations?|offices?)", h, re.I)]
    # Contact pages first: they also list the offices (trading addresses).
    for link in list(dict.fromkeys(contact + extra))[:5]:
        if urllib.parse.urlparse(link).netloc != host:
            continue
        is_contact = link in contact
        if conf == "high" and not is_contact:
            continue
        sub = _fetch(link)
        if not sub:
            continue
        sub_text = _text(sub[1])
        if is_contact:
            found += [{**a, "page": sub[0]} for a in addresses(sub_text) if a["postcode"] not in {f["postcode"] for f in found}]
        c2, w2 = evidence(sub_text, company_number, postcode, names)
        rank = {"high": 3, "medium": 2, "low": 1, None: 0}
        if rank[c2] > rank[conf]:
            conf, why, page = c2, w2, sub[0]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return {"url": final, "reachable": True, "confidence": conf, "evidence": why, "page": page, "addresses": found,
            "title": " ".join(htmlmod.unescape(title.group(1)).split())[:120] if title else None}


def find(names: list[str], company_number: str, postcode: str | None, max_checks: int = 12) -> list[dict]:
    """Try likely domains; return checked sites, best first."""
    out = []
    for d in candidates(names):
        if len(out) >= max_checks:
            break
        if not _resolves(d):
            continue
        r = check("https://" + d, company_number, postcode, names)
        if r["reachable"]:
            out.append(r)
        if r.get("confidence") == "high":
            break
    rank = {"high": 3, "medium": 2, "low": 1, None: 0}
    out.sort(key=lambda r: rank[r["confidence"]], reverse=True)
    return out


def brief(conn, company_number: str) -> dict:
    """Everything useful for finding the company online, with search queries."""
    num = company_number.strip().upper()
    c = conn.execute("select * from company where company_number = %s", (num,)).fetchone()
    if not c:
        return {}
    town = None
    if c["registered_address"]:
        parts = [p.strip() for p in c["registered_address"].split(",") if p.strip()]
        town = next((p for p in reversed(parts[:-1]) if not re.search(r"\d", p)), None) if len(parts) > 1 else None
    owners = conn.execute(
        """select p.name, p.kind, p.registration_number from company_person cp join person p on p.id = cp.person_id
           where cp.company_number = %s and cp.ceased_on is null""", (num,)).fetchall()
    people = [o["name"] for o in owners if o["kind"] == "individual"]
    parents = [o["name"] for o in owners if o["kind"] != "individual"]
    subs = [r["name"] for r in conn.execute(
        """select c2.name from company_person cp join person p on p.id = cp.person_id
           join company c2 on c2.company_number = cp.company_number
           where p.registration_number = %s and cp.ceased_on is null limit 10""", (num,)).fetchall()]
    prev = [p["name"] for p in (c["previous_names"] or [])]
    sics = [r["description"] for r in conn.execute(
        "select description from sic_code where code = any(%s)", (c["sic_codes"] or [],)).fetchall()]
    short = " ".join(_SUFFIX.sub(" ", c["name"]).split()) or c["name"]
    q = [f'"{short}" {town or ""}'.strip(), f'"{short}" "{c["postcode"]}"' if c["postcode"] else None,
         f'"{num}" {short}', f'"{short}" site:linkedin.com/company']
    q += [f'"{" ".join(_SUFFIX.sub(" ", n).split())}"' for n in prev[:3]]
    q += [f'"{" ".join(_SUFFIX.sub(" ", n).split())}" {town or ""}'.strip() for n in parents[:2]]
    q += [f'"{re.sub(r"^(MR|MRS|MS|MISS|DR) ", "", p.upper()).title()}" "{short}"' for p in people[:3]]
    return {
        "company_number": num, "name": c["name"], "previous_names": prev, "registered_address": c["registered_address"],
        "postcode": c["postcode"], "town": town, "industry": sics, "owners": people, "parent_companies": parents,
        "subsidiaries": subs, "domain_guesses": candidates([c["name"], *prev, *parents, *subs])[:12],
        "search_queries": [x for x in q if x],
        "how_to_confirm": ("A UK company must show its registered number on its website: look for it in the footer, "
                           "contact, privacy or terms page. Failing that, the registered address or postcode. The site "
                           "may be under a trading name, a previous name, the parent's name or a subsidiary's name. "
                           "Save only a site you have confirmed, with the page as the source."),
    }
