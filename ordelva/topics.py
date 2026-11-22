"""Topic pool, scoring and de-duplication.

Score = interest (Wikipedia pageviews, 60-day mean, log-scaled)
      + media availability bonus
      + pillar weight learned from the channel's own analytics (avg % viewed, views per day)
Topics already produced, or too similar to one already produced, are skipped.
"""
import difflib
import json
import math
from .config import STATE_DIR
from . import state

SEEDS = {
    "history": ["Antikythera mechanism", "Göbekli Tepe", "Nazca Lines", "Voynich manuscript", "Sea Peoples",
                "Late Bronze Age collapse", "Library of Alexandria", "Roanoke Colony", "Mary Celeste",
                "Franklin's lost expedition", "Terracotta Army", "Herculaneum papyri", "Dead Sea Scrolls",
                "Rosetta Stone", "Linear A", "Stonehenge", "Newgrange", "Çatalhöyük", "Great Zimbabwe",
                "Angkor Wat", "Machu Picchu", "Petra", "Ötzi", "Sutton Hoo", "Tollund Man", "Lycurgus Cup",
                "Mohenjo-daro", "Derinkuyu underground city", "Tarim mummies", "Nebra sky disc", "Uluburun shipwreck",
                "Pavlopetri", "Thonis-Heracleion", "Port Royal", "Cahokia", "Phaistos Disc", "Rongorongo",
                "Nan Madol", "Helike", "Meroë", "Hanging Gardens of Babylon", "Lighthouse of Alexandria",
                "Mausoleum of Qin Shi Huang", "Sanxingdui", "Dancing plague of 1518", "Piri Reis map",
                "Baghdad Battery", "Lascaux", "Chauvet Cave", "Kingdom of Aksum"],
    "geography": ["Richat Structure", "Darvaza gas crater", "Danakil Depression", "Socotra", "Lake Hillier",
                  "Blood Falls", "Sailing stones", "Shanay-Timpishka", "Catatumbo lightning", "Morning Glory cloud",
                  "Zealandia", "Challenger Deep", "Lake Baikal", "African humid period", "Beringia",
                  "Lake Agassiz", "Missoula floods", "Zanclean flood", "Messinian salinity crisis", "Lake Nyos disaster",
                  "Eye of the Sahara", "Son Doong cave", "Mount Roraima", "Salar de Uyuni", "Lake Natron"],
    "science": ["Tunguska event", "Carrington Event", "Year Without a Summer", "1883 eruption of Krakatoa",
                "Chicxulub crater", "Snowball Earth", "Natural nuclear fission reactor", "Kola Superdeep Borehole",
                "Vredefort impact structure", "Burgess Shale", "Archaeopteryx", "Coelacanth", "Homo floresiensis",
                "Denisovan", "Piltdown Man", "Wow! signal", "Tardigrade", "Toba catastrophe theory",
                "Storegga Slide", "Doggerland"],
}
PILLAR_OF = {t: p for p, ts in SEEDS.items() for t in ts}
HISTORY_FILE = STATE_DIR / "topics_done.json"


def done():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return []


def mark_done(title, pid, status):
    d = done()
    d.append({"title": title, "id": pid, "status": status})
    HISTORY_FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def too_similar(title, previous, thr=0.82):
    t = title.lower()
    return any(difflib.SequenceMatcher(None, t, p.lower()).ratio() >= thr for p in previous)


def pillar_weights():
    """Learn from published videos: mean avg-view% and views/day per pillar (bounded 0.7..1.4)."""
    s = state.get()
    agg = {}
    for v in s["videos"].values():
        p = v.get("pillar")
        if not p or not v.get("youtube_id"):
            continue
        a = agg.setdefault(p, [])
        a.append((v.get("avg_view_pct") or 50) / 50.0 + math.log10(1 + (v.get("views") or 0)) / 4)
    if not agg:
        return {p: 1.0 for p in SEEDS}
    base = sum(sum(a) / len(a) for a in agg.values()) / len(agg)
    return {p: max(0.7, min(1.4, (sum(agg[p]) / len(agg[p])) / base)) if p in agg else 1.05 for p in SEEDS}


def candidates(n=8):
    """Return untried seed topics ranked by score (pageviews fetched lazily)."""
    from .research import pageviews
    prev = [d["title"] for d in done()]
    w = pillar_weights()
    pool = [t for t in PILLAR_OF if not too_similar(t, prev)]
    # rotate pillars so the channel stays balanced
    recent = [PILLAR_OF.get(d["title"]) for d in done()[-3:]]
    scored = []
    for t in pool:
        pv = pageviews(t)
        p = PILLAR_OF[t]
        score = math.log10(1 + pv) * w.get(p, 1.0) - 0.35 * recent.count(p)
        scored.append((score, t, p, pv))
    scored.sort(reverse=True)
    return [{"title": t, "pillar": p, "pageviews_per_day": round(pv), "score": round(s, 3)} for s, t, p, pv in scored[:n]]
