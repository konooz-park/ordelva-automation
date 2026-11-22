"""Licensed visuals for `image` scenes, with the licence recorded in spec.assets (checked by QA).

Sources (free):
  * Pexels API – free key (https://www.pexels.com/api/), Pexels License: free commercial use, no attribution required.
    Set environment variable PEXELS_API_KEY.  Limit: 200 requests/hour, 20,000/month.
  * Wikimedia Commons – only Public domain / CC0 / CC BY / CC BY-SA files are accepted; attribution is
    added to the video description automatically.
"""
import json
import os
import requests
from .config import PROJECTS, load_config

UA = {"User-Agent": "ORDELVA-Automation/1.0"}
OK_LICENCES = ("public domain", "pd", "cc0", "cc by", "cc-by")


def pexels_photo(query, dest, orientation="portrait"):
    key = os.environ.get(load_config()["pexels_api_key_env"])
    if not key:
        return None
    r = requests.get("https://api.pexels.com/v1/search", headers={"Authorization": key, **UA}, timeout=30,
                     params={"query": query, "orientation": orientation, "per_page": 5}).json()
    for ph in r.get("photos", []):
        img = requests.get(ph["src"]["original"], headers=UA, timeout=60).content
        open(dest, "wb").write(img)
        return {"what": query, "source": ph["url"], "author": ph["photographer"], "licence": "Pexels License"}
    return None


def commons_image(query, dest):
    api = "https://commons.wikimedia.org/w/api.php"
    r = requests.get(api, headers=UA, timeout=30, params={
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
        "gsrlimit": 10, "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 2400,
        "format": "json"}).json()
    for p in sorted(r.get("query", {}).get("pages", {}).values(), key=lambda x: x.get("index", 99)):
        ii = p["imageinfo"][0]
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        if not lic.lower().startswith(OK_LICENCES) or ii.get("width", 0) < 1200:
            continue
        open(dest, "wb").write(requests.get(ii.get("thumburl", ii["url"]), headers=UA, timeout=60).content)
        artist = md.get("Artist", {}).get("value", "")
        return {"what": query, "source": ii["descriptionurl"], "author": artist[:200], "licence": lic}
    return None


def fetch_for_spec(pid):
    """Resolve every `image` scene that has a `query` but no `path`."""
    pdir = PROJECTS / pid
    spec = json.loads((pdir / "spec.json").read_text(encoding="utf-8"))
    (pdir / "media").mkdir(exist_ok=True)
    orient = "portrait" if spec.get("format", "short") == "short" else "landscape"
    for i, b in enumerate(spec["beats"]):
        sc = b["scene"]
        if sc.get("type") == "image" and not sc.get("path"):
            dest = pdir / "media" / f"beat{i:02d}.jpg"
            meta = pexels_photo(sc["query"], dest, orient) or commons_image(sc["query"], dest)
            if not meta:
                sc.update({"type": "title", "title": spec["title"].upper()[:24], "subtitle": ""})
                continue
            sc["path"] = str(dest.relative_to(PROJECTS.parent)).replace("\\", "/")
            spec["assets"].append(meta)
    (pdir / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
    return spec
