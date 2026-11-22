"""Free, keyless research + licensed media from Wikipedia / Wikimedia Commons.

Only files whose licence allows commercial reuse are accepted (public domain, CC0, CC BY, CC BY-SA);
author + licence + source URL are written into spec.assets and the video description.
"""
import datetime
import hashlib
import re
from pathlib import Path
import requests

UA = {"User-Agent": "ORDELVA-Automation/1.1 (https://github.com/konooz-park/ordelva-automation; documentary research bot) python-requests",
      "Accept": "application/json", "Api-User-Agent": "ORDELVA-Automation/1.1 (https://github.com/konooz-park/ordelva-automation)"}
WP = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
OK_LICENCES = re.compile(r"^(public domain|pd|cc0|cc by(-sa)? ?[1-4]\.0|cc by(-sa)?$|cc-by|cc-by-sa)", re.I)
BAD_LICENCE = re.compile(r"(nc|nd|fair use|non-free)", re.I)


def _get(url, params, tries=5):
    import time
    last = ""
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=40)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except (requests.RequestException, ValueError) as e:
            last = str(e)[:200]
        time.sleep(2 ** k)
    raise RuntimeError(f"request failed: {url} ({last})")


def article(title):
    r = _get(WP, {"action": "query", "prop": "extracts|coordinates|pageprops|info|categories", "explaintext": 1,
                  "titles": title, "format": "json", "redirects": 1, "inprop": "url", "cllimit": 50})
    page = next(iter(r["query"]["pages"].values()))
    if "missing" in page:
        raise ValueError(f"No Wikipedia article: {title}")
    text = page.get("extract", "")
    text = re.split(r"\n==\s*(See also|References|Notes|Further reading|External links|Bibliography)\s*==", text)[0]
    coords = page.get("coordinates", [{}])[0] if page.get("coordinates") else None
    cats = [c["title"] for c in page.get("categories", [])]
    return {"title": page["title"], "url": page.get("fullurl", "https://en.wikipedia.org/wiki/" + page["title"].replace(" ", "_")),
            "text": text, "coords": {"lat": coords["lat"], "lon": coords["lon"]} if coords else None,
            "disambiguation": "disambiguation" in page.get("pageprops", {}), "categories": cats}


def pageviews(title, days=60):
    end = datetime.date.today() - datetime.timedelta(days=1)
    start = end - datetime.timedelta(days=days)
    t = title.replace(" ", "_")
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
           f"{requests.utils.quote(t, safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}")
    try:
        r = requests.get(url, headers=UA, timeout=30).json()
        return sum(i["views"] for i in r.get("items", [])) / max(1, days)
    except Exception:
        return 0.0


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def article_media(title, dest_dir: Path, limit=14, min_width=900):
    """Licensed images used in the article (most relevant first), downloaded to dest_dir."""
    r = _get(WP, {"action": "query", "generator": "images", "titles": title, "gimlimit": 60, "prop": "imageinfo",
                  "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 2200, "format": "json", "redirects": 1})
    pages = list(r.get("query", {}).get("pages", {}).values())
    return _accept(pages, dest_dir, limit, min_width)


def commons_search(query, dest_dir: Path, limit=6, min_width=1200):
    r = _get(COMMONS, {"action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
                       "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                       "iiurlwidth": 2200, "format": "json"})
    pages = sorted(r.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    return _accept(pages, dest_dir, limit, min_width)


def _accept(pages, dest_dir, limit, min_width):
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for p in pages:
        if len(out) >= limit:
            break
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/tiff"):
            continue
        name = p["title"].lower()
        if any(k in name for k in ("logo", "icon", "flag of", "symbol", "commons-", "wiki", "edit-", "question_book",
                                   "padlock", "ambox", "map pointer", "locator", "red pog")):
            continue
        if ii.get("width", 0) < min_width or ii.get("height", 0) < 500:
            continue
        md = ii.get("extmetadata", {})
        lic = _strip_html(md.get("LicenseShortName", {}).get("value", ""))
        if not lic or BAD_LICENCE.search(lic) or not OK_LICENCES.search(lic):
            continue
        if md.get("Restrictions", {}).get("value"):
            continue  # trademark / personality rights etc.
        url = ii.get("thumburl") or ii["url"]
        try:
            data = requests.get(url, headers=UA, timeout=60).content
        except requests.RequestException:
            continue
        fn = dest_dir / (hashlib.sha1(url.encode()).hexdigest()[:12] + ".jpg")
        fn.write_bytes(data)
        desc = _strip_html(md.get("ImageDescription", {}).get("value", ""))[:160]
        out.append({"path": fn, "what": desc or p["title"].replace("File:", ""), "source": ii.get("descriptionurl"),
                    "author": _strip_html(md.get("Artist", {}).get("value", ""))[:120] or "unknown",
                    "licence": lic, "width": ii.get("width"), "height": ii.get("height")})
    return out
