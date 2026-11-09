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


def _person_parts(name: str) -> tuple[str, str] | None:
    """(first name, surname) from "HARRIS, John Michael" or "Mr John Michael Harris"."""
    n = re.sub(r"^(MR|MRS|MS|MISS|DR|SIR|PROF)\.?\s+", "", (name or "").strip(), flags=re.I)
    if "," in n:
        last, rest = n.split(",", 1)
        first = (rest.split() or [""])[0]
    else:
        w = n.split()
        if len(w) < 2:
            return None
        first, last = w[0], w[-1]
    clean = lambda x: re.sub(r"[^a-z]", "", x.lower())
    return (clean(first), clean(last)) if clean(last) else None


def extra_stems(name: str, people: list[str] | None = None, town: str | None = None) -> list[str]:
    """Domains small firms often use that aren't their registered name: the
    owner's surname with the trade ("harrisjoinery"), "harrisandsons", the
    owner's full name, and the name or trade with the town."""
    words = [w for w in re.sub(r"[^a-z0-9 ]+", " ", _SUFFIX.sub(" ", re.sub(r"&", " and ", name or "")).lower()).split()]
    trade = words[-1] if words and len(words[-1]) >= 4 else None
    out: list[str] = []
    for p in (people or [])[:3]:
        parts = _person_parts(p)
        if not parts:
            continue
        first, last = parts
        if trade and trade != last:
            out += [last + trade, f"{last}-{trade}"]
        out += [last + "andsons", first + last]
    t = re.sub(r"[^a-z]", "", (town or "").lower())
    if t and words:
        out += ["".join(words) + t]
        if trade:
            out += [t + trade, f"{t}-{trade}"]
    seen: list[str] = []
    for x in out:
        if 4 <= len(x) <= 40 and x not in seen:
            seen.append(x)
    return seen


def candidates(names: list[str], limit: int = 16, people: list[str] | None = None, town: str | None = None) -> list[str]:
    out: list[str] = []
    for n in names:
        for stem in name_stems(n):
            for tld in TLDS:
                d = stem + tld
                if d not in out:
                    out.append(d)
    out = out[:limit]
    # Then guesses from the owners and the town, on the two usual endings.
    for stem in extra_stems(names[0] if names else "", people, town):
        for tld in (".co.uk", ".com"):
            if stem + tld not in out:
                out.append(stem + tld)
    return out


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
        with urllib.request.urlopen(req, timeout=6) as r:
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


def _number_re(company_number: str):
    num = company_number.upper()
    digits = num.lstrip("0") if num.isdigit() else num
    return re.compile(r"(?<![0-9])0*" + re.escape(digits) + r"(?![0-9])") if num.isdigit() else re.compile(re.escape(num), re.I)


def registered_name_found(text: str, name: str) -> bool:
    """The registered name with its LIMITED/LTD (or PLC/LLP) ending, as UK
    companies must show it, e.g. "Example Systems Ltd" for EXAMPLE SYSTEMS LIMITED."""
    t = " ".join(text.split())
    m = re.match(r"^(.*?)[\s,.]*\b(LIMITED|LTD|PLC|LLP)\.?$", (name or "").strip(), re.I)
    if not m or len(m.group(1)) < 2:
        return False
    words = m.group(1).replace("&", " & ").replace(".", " ").split()
    core = r"[\s.]+".join("(?:&|and)" if w.upper() in ("&", "AND") else re.escape(w) for w in words)
    end = {"LIMITED": "(?:limited|ltd)", "LTD": "(?:limited|ltd)", "PLC": "plc", "LLP": "llp"}[m.group(2).upper()]
    return bool(re.search(r"\b" + core + r",?\s+" + end + r"\b\.?", t, re.I))


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


_PARKED = re.compile(r"(this domain (is|may be) for sale|domain (is )?parked|buy this domain|parkingcrew|sedoparking|"
                     r"domain has been registered|coming soon|under construction|web hosting by)", re.I)


def check(url: str, company_number: str, postcode: str | None, names: list[str]) -> dict:
    """Fetch a site's home page (and its contact/about/legal pages if needed)
    and say how sure we are it belongs to the company."""
    if not re.match(r"^https?://", url):
        url = "https://" + url.strip().lstrip("/")
    got = _fetch(url) or (_fetch(url.replace("https://", "http://", 1)) if url.startswith("https://") else None)
    if not got:
        return {"url": url, "reachable": False, "confidence": None, "evidence": "site did not answer"}
    final, html = got
    home_text = _text(html)
    if _PARKED.search(home_text[:3000]) and len(home_text) < 4000:
        return {"url": final, "reachable": True, "confidence": None, "evidence": "parked or for-sale domain", "addresses": []}
    conf, why = evidence(home_text, company_number, postcode, names)
    page = final
    # Strict confirmation: the company number AND the registered name (with
    # Ltd/Limited) somewhere on the site's pages we read.
    num_re = _number_re(company_number)
    reg_name = names[0] if names else ""
    has_number, has_name = bool(num_re.search(home_text)), registered_name_found(home_text, reg_name)
    found = [{**a, "page": final} for a in addresses(_text(html))]
    links = re.findall(r'href="([^"#]+)"', html, re.I)
    host = urllib.parse.urlparse(final).netloc
    contact = [urllib.parse.urljoin(final, h) for h in links if re.search(r"(contact|locations?|offices?|find-us)", h, re.I)]
    extra = [urllib.parse.urljoin(final, h) for h in links
             if re.search(r"(contact|about|privacy|terms|legal|cookie|imprint|locations?|offices?)", h, re.I)]
    # Contact pages first: they also list the offices (trading addresses).
    from concurrent.futures import ThreadPoolExecutor

    todo = [l for l in list(dict.fromkeys(contact + extra))[:5] if urllib.parse.urlparse(l).netloc == host
            and not (has_number and has_name and l not in contact)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        subs = list(zip(todo, pool.map(_fetch, todo)))
    for link, sub in subs:
        is_contact = link in contact
        if not sub:
            continue
        sub_text = _text(sub[1])
        has_number = has_number or bool(num_re.search(sub_text))
        has_name = has_name or registered_name_found(sub_text, reg_name)
        if is_contact:
            found += [{**a, "page": sub[0]} for a in addresses(sub_text) if a["postcode"] not in {f["postcode"] for f in found}]
        c2, w2 = evidence(sub_text, company_number, postcode, names)
        rank = {"high": 3, "medium": 2, "low": 1, None: 0}
        if rank[c2] > rank[conf]:
            conf, why, page = c2, w2, sub[0]
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    strict = has_number and has_name
    if strict:
        why = f"company number {company_number.upper()} and the registered name are both on the site"
    return {"url": final, "reachable": True, "confidence": conf, "evidence": why, "page": page, "addresses": found,
            "strict": strict, "has_number": has_number, "has_name": has_name,
            "title": " ".join(htmlmod.unescape(title.group(1)).split())[:120] if title else None}


def find(names: list[str], company_number: str, postcode: str | None, max_checks: int = 12,
         strict: bool = False, people: list[str] | None = None, town: str | None = None) -> list[dict]:
    """Try likely domains; return checked sites, best first. Every guess is
    looked up at once (most don't exist), then the live ones are read a few at
    a time, most likely first, stopping once one is confirmed."""
    from concurrent.futures import ThreadPoolExecutor

    doms = candidates(names, people=people, town=town)
    with ThreadPoolExecutor(max_workers=16) as pool:
        live = [d for d, ok in zip(doms, pool.map(_resolves, doms)) if ok][:max_checks]
    out = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i in range(0, len(live), 4):
            batch = list(pool.map(lambda d: check("https://" + d, company_number, postcode, names), live[i:i + 4]))
            out += [r for r in batch if r["reachable"]]
            if any(r.get("strict") or (not strict and r.get("confidence") == "high") for r in batch):
                break
    rank = {"high": 3, "medium": 2, "low": 1, None: 0}
    out.sort(key=lambda r: (bool(r.get("strict")), rank[r["confidence"]]), reverse=True)
    return out


def add_offices(conn, num: str, registered_postcode: str | None, result: dict, confidence: str = "high") -> list[dict]:
    """Offices listed on the company's own site, added to any already saved
    (the registered office is skipped). Returns the ones added."""
    from . import enrich

    cur = conn.execute("select locations from enrichment where company_number = %s", (num,)).fetchone()
    locs = list((cur or {}).get("locations") or [])
    have = {l.get("postcode") for l in locs} | {registered_postcode}
    new = []
    for a in result.get("addresses") or []:
        if a["postcode"] not in have:
            have.add(a["postcode"])
            new.append(a)
    if new:
        locs += [{"kind": "office", "name": None, "address": a["address"], "postcode": a["postcode"]} for a in new]
        enrich.save_enrichment(conn, num, source_url=new[0]["page"], locations=locs, confidence=confidence,
                               source_label="Offices listed on the company's website", by="website check")
    return new


def bulk_check(conn, numbers: list[str], progress=None, cancel=None, workers: int = 12) -> dict:
    """Find and confirm websites for many companies, several at a time. A site
    is saved only when it shows both the company number and the registered
    name (Ltd/Limited), with any office addresses listed on it. Weaker matches
    are kept as "possible, not confirmed" research notes for you to check.
    Each company tried is recorded (website_check), so a stopped run carries on."""
    from concurrent.futures import ThreadPoolExecutor

    from . import enrich

    stats = {"checked": 0, "confirmed": 0, "possible": 0, "none": 0}

    def look(b):
        names = [b["name"], *b["previous_names"], *b["parent_companies"], *b["subsidiaries"]]
        try:
            return b, find(names, b["company_number"], b["postcode"], max_checks=8, strict=True,
                           people=b.get("owners"), town=b.get("town"))
        except Exception:
            return b, []

    def save(b, results):
        num = b["company_number"]
        best = next((r for r in results if r.get("strict")), None)
        if best:
            enrich.save_enrichment(conn, num, source_url=best.get("page") or best["url"], website=best["url"], confidence="high",
                                   source_label="Website check: company number and registered name on the site", by="website check")
            add_offices(conn, num, b["postcode"], best)
            result = "confirmed"
        else:
            maybe = next((r for r in results if r.get("confidence") in ("high", "medium")), None)
            if maybe:
                conn.execute(
                    """insert into research (company_number, kind, content, source_url, source_label, created_by, confidence)
                       values (%s, 'website', %s, %s, 'Website check', 'website check', 'low')""",
                    (num, f"Possible website, not confirmed: {maybe['url']} ({maybe['evidence']}). "
                          "Saved only once the company number and registered name are both found.", maybe["url"]))
                result = "possible"
            else:
                result = "none"
        conn.execute("""insert into website_check (company_number, result) values (%s, %s)
                        on conflict (company_number) do update set result = excluded.result, checked_at = now()""",
                     (num, result))
        stats[result] += 1
        stats["checked"] += 1

    total = max(len(numbers), 1)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # Feed the pool a chunk at a time; the database work stays on this thread.
        for start in range(0, len(numbers), workers * 4):
            if cancel:
                cancel()
            briefs = [b for b in (brief(conn, n) for n in numbers[start:start + workers * 4]) if b]
            for b, results in pool.map(look, briefs):
                save(b, results)
            conn.commit()
            if progress:
                progress(stats["checked"] / total,
                         f"{stats['checked']:,} of {len(numbers):,} · {stats['confirmed']:,} confirmed, "
                         f"{stats['possible']:,} possible")
    return stats


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
        "subsidiaries": subs, "domain_guesses": candidates([c["name"], *prev, *parents, *subs], people=people, town=town)[:20],
        "search_queries": [x for x in q if x],
        "how_to_confirm": ("A UK company must show its registered number on its website: look for it in the footer, "
                           "contact, privacy or terms page. Failing that, the registered address or postcode. The site "
                           "may be under a trading name, a previous name, the parent's name or a subsidiary's name. "
                           "Save only a site you have confirmed, with the page as the source."),
    }
