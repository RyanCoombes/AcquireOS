"""Company logos from each company's own website, kept on this server.

Looks at the home page for, in order: the home-screen icon
(apple-touch-icon), a large or SVG icon, an image named "logo" that is
roughly square, then /apple-touch-icon.png and /favicon.ico. The first one
that is at least 32px is resized to a small PNG and saved (SVGs are kept as
they are). Tiny 16px favicons are not used: the app shows initials instead.
Nothing is fetched from a third-party logo service.
"""
from __future__ import annotations

import html as htmlmod
import io
import queue
import re
import threading
import urllib.parse
import urllib.request

from .website import UA, _fetch

MIN_PX = 32          # smaller than this looks blurry: initials instead
MAX_PX = 128         # stored size
MAX_BYTES = 400_000  # per image fetched
RETRY_DAYS = 30      # a site with no usable logo is tried again after this
RECHECK_DAYS = 182   # a logo found on the website is looked at again after this (a rebrand)

_TAG = re.compile(r"<(link|img|meta)\b([^>]*)>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")


def _attrs(s: str) -> dict:
    return {m.group(1).lower(): htmlmod.unescape(m.group(3) or m.group(4) or m.group(5) or "") for m in _ATTR.finditer(s)}


def candidates(page_url: str, html: str) -> list[str]:
    """Image URLs worth trying, best first."""
    scored: list[tuple[int, int, str]] = []
    for i, m in enumerate(_TAG.finditer(html[:400_000])):
        tag, a = m.group(1).lower(), _attrs(m.group(2))
        if tag == "link":
            rel = a.get("rel", "").lower()
            href = a.get("href")
            if not href or "icon" not in rel or "mask-icon" in rel:
                continue
            sizes = [int(x) for x in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
            size = max(sizes) if sizes else 0
            if "apple-touch-icon" in rel:
                score = 400 + min(size, 200)
            elif href.lower().split("?")[0].endswith(".svg") or "svg" in a.get("type", ""):
                score = 350
            else:
                score = 100 + min(size, 200) if size else 60
        elif tag == "img":
            src = _img_src(a)
            hint = " ".join(a.get(k, "") for k in ("src", "alt", "class", "id", "data-src", "data-lazy-src", "srcset")).lower()
            if not src or "logo" not in hint:
                continue
            score = 300 - min(i, 200) // 10  # earlier on the page (the header) is better
            href = src
        elif tag == "meta":  # a share image named "logo" (not a photo)
            prop = (a.get("property") or a.get("name") or "").lower()
            src = a.get("content") or ""
            if prop not in ("og:image", "twitter:image", "og:logo") or ("logo" not in src.lower() and prop != "og:logo"):
                continue
            score, href = 200, src
        else:
            continue
        if tag == "link":
            href = a.get("href")
        scored.append((score, -i, urllib.parse.urljoin(page_url, href)))
    out = [u for _, _, u in sorted(scored, reverse=True)]
    root = urllib.parse.urljoin(page_url, "/")
    for extra in ("apple-touch-icon.png", "favicon.ico"):
        u = root + extra
        if u not in out:
            out.append(u)
    return [u for u in out if u.startswith(("http://", "https://"))][:8]


def _img_src(a: dict) -> str | None:
    """An <img>'s real address, including lazy-loaded and srcset-only ones."""
    for k in ("src", "data-src", "data-lazy-src", "data-original"):
        v = a.get(k)
        if v and not v.startswith("data:"):
            return v
    for k in ("srcset", "data-srcset", "data-lazy-srcset"):
        v = a.get(k)
        if v:
            return v.split(",")[-1].strip().split(" ")[0] or None  # the largest listed
    return None


def manifest_icons(page_url: str, html: str) -> list[str]:
    """Icons from the site's web app manifest (often the only large one: 192 or 512px)."""
    m = re.search(r"""<link\b[^>]*rel=["']?manifest["']?[^>]*>""", html[:400_000], re.I)
    href = _attrs(m.group(0)).get("href") if m else None
    if not href:
        return []
    url = urllib.parse.urljoin(page_url, href)
    got = _get(url, accept="application/manifest+json, application/json")
    if not got:
        return []
    try:
        import json
        icons = json.loads(got[0].decode("utf-8", "replace")).get("icons") or []
    except Exception:
        return []
    def size(i):
        return max([int(x) for x in re.findall(r"(\d+)x\d+", str(i.get("sizes") or ""))] or [0])
    icons = [i for i in icons if isinstance(i, dict) and i.get("src") and "monochrome" not in str(i.get("purpose") or "")]
    return [urllib.parse.urljoin(url, i["src"]) for i in sorted(icons, key=size, reverse=True)][:2]


def _get(url: str, accept: str = "image/*") -> tuple[bytes, str] | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES or not data:
                return None
            return data, (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except Exception:
        return None


def _svg_ok(data: bytes) -> bool:
    head = data[:2000].decode("utf-8", errors="ignore").lower()
    return "<svg" in head or ("<?xml" in head and "svg" in head)


def normalise(data: bytes, content_type: str, url: str, chosen: bool = False) -> dict | None:
    """A small PNG (or the SVG as-is) if the image is usable, else None. An
    image you chose yourself may be any shape and as small as 16px."""
    if "svg" in content_type or url.lower().split("?")[0].endswith(".svg"):
        if not _svg_ok(data) or len(data) > 150_000:
            return None
        return {"image": data, "content_type": "image/svg+xml", "width": None}
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if getattr(im, "format", "") == "ICO":
            im.size = max(im.ico.sizes())  # the largest picture in the .ico
        im.load()
    except Exception:
        return None
    w, h = im.size
    if min(w, h) < (16 if chosen else MIN_PX):
        return None
    if not chosen and max(w, h) / max(1, min(w, h)) > 2.5:  # a long wordmark: unreadable in a small square
        return None
    im = im.convert("RGBA")
    im.thumbnail((MAX_PX, MAX_PX))
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return {"image": out.getvalue(), "content_type": "image/png", "width": im.size[0]}


def find(website: str) -> dict | None:
    """The best logo on a website, or None."""
    return find_with_reason(website)[0]


def find_with_reason(website: str) -> tuple[dict | None, str | None]:
    """(the best logo, None) or (None, why there's none). Square icons first; a wide
    logo (a wordmark) only when nothing square and at least 32px is found."""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    page = _fetch(website)
    page_url, html = page if page else (website, "")
    urls = candidates(page_url, html)
    if html:
        man = manifest_icons(page_url, html)
        # the home-screen icon stays first; the manifest's large icons next
        touch = [u for u in urls[:1] if "apple-touch-icon" in u]
        urls = touch + man + [u for u in urls if u not in man and u not in touch]
    seen, wide, small, loaded = set(), None, False, 0
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        got = _get(url)
        if not got:
            continue
        loaded += 1
        img = normalise(got[0], got[1], url)
        if img:
            return {**img, "source_url": url}, None
        if wide is None:
            w = normalise(got[0], got[1], url, chosen=True)
            if w and (w["width"] is None or w["width"] >= MIN_PX):
                wide = {**w, "source_url": url}
            elif w:
                small = True
    if wide:
        return wide, None
    if not page:
        return None, "The website didn't answer (or blocked the request)"
    if small:
        return None, "Only a tiny icon (under 32px), which would look blurred"
    if not loaded:
        return None, "No logo or icon on the home page"
    return None, "No usable image (wrong format)"


def stored(conn, num: str) -> tuple[dict | None, bool]:
    """(the stored logo or None, whether it should be fetched). Fetch when the
    company has a website and it has not been tried, its website changed, or
    a try that found nothing is over RETRY_DAYS old, or a logo it found is over
    RECHECK_DAYS old (the stored one keeps showing meanwhile)."""
    row = conn.execute("""select e.website as site, l.status, l.image, l.content_type, l.website, l.manual, l.fetched_at,
                                 coalesce(l.checked_at, l.fetched_at) < now() - make_interval(days => %s) as old,
                                 coalesce(l.checked_at, l.fetched_at) < now() - make_interval(days => %s) as stale
                            from company c left join enrichment e using (company_number)
                            left join company_logo l using (company_number)
                           where c.company_number = %s""", (RETRY_DAYS, RECHECK_DAYS, num)).fetchone()
    if row and row["manual"]:  # chosen or removed by you: left alone
        return (row if row["status"] == "found" else None), False
    if not row or not row["site"]:
        return None, False
    if row["status"] and row["website"] == row["site"]:
        if row["status"] == "found":
            return row, bool(row["stale"])
        return None, bool(row["old"])
    return None, True


def save(conn, num: str, *, image: dict | None, source_url: str | None, manual: bool) -> None:
    site = conn.execute("select website from enrichment where company_number = %s", (num,)).fetchone()
    conn.execute("""insert into company_logo (company_number, website, status, image, content_type, source_url, width, manual, fetched_at, checked_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    on conflict (company_number) do update set website = excluded.website, status = excluded.status,
                        image = excluded.image, content_type = excluded.content_type, source_url = excluded.source_url,
                        width = excluded.width, manual = excluded.manual, fetched_at = now(), checked_at = now()""",
                 (num, (site and site["website"]) or "", "found" if image else "none", image and image["image"],
                  image and image["content_type"], source_url, image and image["width"], manual))


def from_url(url: str) -> dict:
    """An image you point to: fetched and resized, or a ValueError saying why not."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    got = _get(url)
    if not got:
        raise ValueError("That address couldn't be downloaded (or the image is over 400 KB).")
    img = normalise(got[0], got[1], url, chosen=True)
    if not img:
        raise ValueError("That address isn't an image that can be used (PNG, JPEG, WebP, GIF, ICO or SVG, at least 16px).")
    return img


def fetch_and_store(num: str) -> bool:
    """Fetch one company's logo from its website and save the result."""
    from . import db
    with db.conn() as c:
        r = c.execute("select website from enrichment where company_number = %s", (num,)).fetchone()
    site = r and r["website"]
    if not site:
        return False
    found, note = find_with_reason(site)  # no database connection held while fetching
    with db.conn() as c:
        old = c.execute("select website, status, image, manual from company_logo where company_number = %s", (num,)).fetchone()
        if old and old["manual"]:
            return False
        if old and old["website"] == site and old["status"] == "found" and (
                not found or bytes(old["image"]) == found["image"]):
            # A re-check: the same logo (or the site didn't answer this time): keep it as it is,
            # so its version, and the copy in your browser, stay the same.
            c.execute("update company_logo set checked_at = now() where company_number = %s", (num,))
            return True
        c.execute("""insert into company_logo (company_number, website, status, image, content_type, source_url, width, note, fetched_at, checked_at)
                     values (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                     on conflict (company_number) do update set website = excluded.website, status = excluded.status,
                         image = excluded.image, content_type = excluded.content_type, source_url = excluded.source_url,
                         width = excluded.width, note = excluded.note, fetched_at = now(), checked_at = now()
                     where not company_logo.manual""",
                  (num, site, "found" if found else "none", found and found["image"], found and found["content_type"],
                   found and found["source_url"], found and found["width"], note))
    return bool(found)


# A small background queue: pages ask for logos, a few threads fetch them,
# so opening a page never waits on someone else's website.
_queue: "queue.Queue[str]" = queue.Queue()
_queued: set[str] = set()
_lock = threading.Lock()
_started = False
WORKERS = 3


def _work():
    while True:
        num = _queue.get()
        try:
            fetch_and_store(num)
        except Exception:
            pass
        finally:
            with _lock:
                _queued.discard(num)


def recheck_stale(conn, numbers: list[str]) -> None:
    """Queue a look at the website for logos it found over RECHECK_DAYS ago,
    among these companies (the ones a page is showing). Browsers keep logos
    for good, so this is how a rebrand is picked up."""
    if not numbers:
        return
    for r in conn.execute("""select company_number from company_logo
                             where company_number = any(%s) and status = 'found' and not manual
                               and coalesce(checked_at, fetched_at) < now() - make_interval(days => %s)""",
                          (list(numbers), RECHECK_DAYS)):
        request(r["company_number"])


def request(num: str) -> None:
    global _started
    with _lock:
        if num in _queued:
            return
        _queued.add(num)
        if not _started:
            for _ in range(WORKERS):
                threading.Thread(target=_work, daemon=True, name="logo-fetch").start()
            _started = True
    _queue.put(num)


def todo(conn) -> list[str]:
    """Companies with a website whose logo hasn't been looked for, whose website
    changed, or where nothing was found over RETRY_DAYS ago."""
    return [r["company_number"] for r in conn.execute(
        """select e.company_number from enrichment e left join company_logo l using (company_number)
           where e.website is not null and coalesce(l.manual, false) = false
             and (l.company_number is null or l.website is distinct from e.website
                  or (l.status = 'none' and coalesce(l.checked_at, l.fetched_at) < now() - make_interval(days => %s)))
           order by e.company_number""", (RETRY_DAYS,))]


def summary(conn) -> dict:
    r = conn.execute("""select count(*) filter (where e.website is not null) as with_website,
                               count(*) filter (where l.status = 'found') as found,
                               count(*) filter (where l.status = 'none' and not l.manual) as none,
                               count(*) filter (where l.manual) as yours
                        from enrichment e left join company_logo l using (company_number)""").fetchone()
    reasons = conn.execute("""select coalesce(note, 'Not recorded (looked for before reasons were kept)') as note, count(*) as n
                              from company_logo where status = 'none' and not manual group by 1 order by 2 desc""").fetchall()
    return {**r, "not_tried": len(todo(conn)), "reasons": reasons}


def find_all(progress=None, workers: int = 4) -> dict:
    """Look for every missing logo (see todo), a few websites at a time."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from . import db
    with db.conn() as c:
        nums = todo(c)
    found = done = 0
    with ThreadPoolExecutor(workers) as pool:
        futs = [pool.submit(fetch_and_store, n) for n in nums]
        for f in as_completed(futs):
            done += 1
            try:
                found += bool(f.result())
            except Exception:
                pass
            if progress and (done % 10 == 0 or done == len(nums)):
                progress(done / max(len(nums), 1), f"Looked at {done:,} of {len(nums):,} websites: {found:,} logos found")
    return {"looked_at": done, "found": found}
