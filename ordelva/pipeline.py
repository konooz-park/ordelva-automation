"""Autonomous pipeline: topic -> research -> script -> fact check -> render -> strict QA -> publish -> verify.

Entry points (used by GitHub Actions through `python -m ordelva.cli cloud --mode ...`):
  daily              produce today's quota of shorts (ramp-up aware) + weekly long when enabled
  publish-existing   render + QA + upload a hand-made spec (e.g. doggerland-short): private -> verify -> public
  report             weekly report issue
"""
import datetime
import json
import re
import shutil
from .config import PROJECTS, OUTPUT, STATE_DIR, load_config
from . import state, notify
from .state import log

BASE_ASSETS = [
    {"what": "Narration voice", "source": "Kokoro-82M (hexgrad) via kokoro-onnx", "licence": "Apache-2.0"},
    {"what": "Music and sound effects", "source": "ordelva/audio.py (original)", "licence": "Owned by channel"},
    {"what": "Maps", "source": "NOAA ETOPO + GLOBE land mask", "licence": "Public domain"},
    {"what": "Fonts", "source": "Cinzel, Montserrat, Anton", "licence": "SIL Open Font License 1.1"},
]
RUNS_FILE = STATE_DIR / "runs.json"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def _runs():
    return json.loads(RUNS_FILE.read_text(encoding="utf-8")) if RUNS_FILE.exists() else []


def _log_run(entry):
    r = _runs()
    r.append(entry)
    RUNS_FILE.write_text(json.dumps(r[-500:], indent=1, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ build spec
def build_spec(pid, topic, art, media, script, fmt):
    beats, used = [], []
    for b in script["beats"]:
        sc = dict(b.get("scene") or {})
        t = sc.get("type")
        if t == "image":
            k = sc.get("media")
            if not isinstance(k, int) or not (0 <= k < len(media)):
                k = len(beats) % len(media) if media else None
            if k is None:
                sc = {"type": "title", "title": topic["title"].upper()[:22]}
            else:
                m = media[k]
                lic = m["licence"]
                author = re.sub(r"\s+", " ", m["author"])[:40]
                sc = {"type": "image", "path": str(m["path"]), "credit": f"{author} / {lic}" if author != "unknown" else lic}
                used.append(k)
        elif t == "map_pin":
            if not art["coords"]:
                sc = {"type": "title", "title": topic["title"].upper()[:22]}
            else:
                sc = {"type": "map_pin", "lat": art["coords"]["lat"], "lon": art["coords"]["lon"],
                      "name": topic["title"][:28]}
        elif t == "landscape":
            sc = {"type": "landscape", "mood": sc.get("mood", "dawn"), "label": (sc.get("label") or "")[:30],
                  "disclaimer": "ILLUSTRATION"}
        else:
            sc = {"type": "title", "title": (sc.get("title") or topic["title"]).upper()[:22],
                  "subtitle": (sc.get("subtitle") or "")[:40].upper()}
        beats.append({"text": b["text"].strip(), "say": (b.get("say") or b["text"]).strip(), "scene": sc,
                      "sfx": ["whoosh"] if beats else []})
    # title cards always sit on a blurred background (never plain black)
    for i, b in enumerate(beats):
        if b["scene"]["type"] == "title" and "bg" not in b["scene"]:
            near = [beats[j]["scene"] for j in sorted(range(len(beats)), key=lambda j: abs(j - i))
                    if beats[j]["scene"]["type"] in ("image", "map_pin")]
            bg = dict(near[0]) if near else {"type": "landscape", "mood": "dusk"}
            bg.pop("credit", None)
            bg["note"] = False
            b["scene"]["bg"] = bg
    assets = list(BASE_ASSETS)
    credits = []
    for k in sorted(set(used)):
        m = media[k]
        assets.append({"what": m["what"][:120], "source": m["source"], "author": m["author"], "licence": m["licence"]})
        credits.append(f"- {m['author'][:60]} – {m['licence']} – {m['source']}")
    y = script.get("youtube", {})
    desc = y.get("description", "").strip()
    if "Sources" not in desc:
        desc += f"\n\nSources:\n- {art['url']}"
    if credits:
        desc += "\n\nImage credits (Wikimedia Commons):\n" + "\n".join(credits)
    desc += "\n\nNarration: AI voice (Kokoro TTS). Music: original. Maps: NOAA ETOPO."
    title = y.get("title") or topic["title"]
    if fmt == "short" and "#shorts" not in title.lower():
        title = (title[:90] + " #shorts")
    spec = {"id": pid, "format": fmt, "title": topic["title"], "pillar": topic.get("pillar"),
            "voice": load_config()["voice"], "voice_lang": "en-gb", "speed": 1.05 if fmt == "short" else 1.0,
            "music": {"mood": "mystery" if topic.get("pillar") != "geography" else "wonder",
                      "seed": abs(hash(pid)) % 1000},
            "tail": 1.2, "beats": beats,
            "facts": [{"claim": f.get("claim"), "quote": f.get("quote"), "sources": [art["url"]]} for f in script.get("facts", [])],
            "assets": assets,
            "youtube": {"title": title[:100], "description": desc[:4800], "tags": [t[:30] for t in y.get("tags", [])][:12],
                        "category_id": "27", "contains_synthetic_media": True, "made_for_kids": False},
            "thumbnail": {"lines": [l.upper()[:18] for l in script.get("thumbnail_lines", [])][:3] or [topic["title"].upper()[:18]]},
            "source_url": art["url"]}
    return spec


def _word_count(beats):
    return sum(len(b["text"].split()) for b in beats)


def produce(topic, fmt="short"):
    """Full autonomous production of one video. Returns (pid, decision)."""
    from .research import article, article_media, commons_search
    from .llm import write_script, expand_script
    from .factcheck import check
    from .render import render
    from .thumbnail import make
    from .autoqa import decide
    from .topics import mark_done
    today = datetime.date.today()
    pid = f"{today:%Y%m%d}-{_slug(topic['title'])}{'-long' if fmt == 'long' else ''}"
    pdir = PROJECTS / pid
    pdir.mkdir(parents=True, exist_ok=True)
    state.upsert_video(pid, title=topic["title"], format=fmt, status="researching", pillar=topic.get("pillar"))
    art = article(topic["title"])
    if art["disambiguation"] or len(art["text"]) < 2500:
        mark_done(topic["title"], pid, "skipped-thin-source")
        state.upsert_video(pid, status="skipped", reason="source too thin")
        return pid, "skip"
    media = article_media(art["title"], pdir / "media", limit=14 if fmt == "short" else 30)
    if len(media) < 4:
        media += commons_search(art["title"], pdir / "media", limit=6 - len(media))
    if len(media) < 3:
        mark_done(topic["title"], pid, "skipped-no-licensed-media")
        state.upsert_video(pid, status="skipped", reason="fewer than 3 commercially licensed images")
        return pid, "skip"
    notes = art["text"][:16000 if fmt == "long" else 11000]
    lo, hi = (95, 160) if fmt == "short" else (850, 1400)
    script, fact_rep = None, None
    for attempt in range(3):
        style = ""
        if fact_rep:
            style = "PREVIOUS DRAFT WAS REJECTED BY THE FACT-CHECKER FOR:\n- " + "\n- ".join(fact_rep["problems"][:12]) + \
                    "\nFix every problem: remove or re-source those statements."
        script = write_script({"title": art["title"], "url": art["url"]}, notes,
                              [{"what": m["what"]} for m in media], art["coords"], fmt, style)
        spec = build_spec(pid, topic, art, media, script, fmt)
        wc = _word_count(spec["beats"])
        if wc < lo:
            script = expand_script(script, notes, "120-140" if fmt == "short" else "1000-1200")
            spec = build_spec(pid, topic, art, media, script, fmt)
            wc = _word_count(spec["beats"])
        if not (lo <= wc <= hi):
            fact_rep = {"ok": False, "problems": [f"narration has {wc} words; required {lo}-{hi}"]}
            continue
        (pdir / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
        fact_rep = check(spec, art["text"])
        (pdir / "factcheck.json").write_text(json.dumps(fact_rep, indent=1, ensure_ascii=False), encoding="utf-8")
        if fact_rep["ok"]:
            break
    if not fact_rep or not fact_rep["ok"]:
        mark_done(topic["title"], pid, "held-facts")
        state.upsert_video(pid, status="held", qa_failures=(fact_rep or {}).get("problems", [])[:10])
        notify.alert(f"Held before render: {topic['title']}", "Fact check could not be passed after 3 drafts.\n\n- " +
                     "\n- ".join((fact_rep or {}).get("problems", [])[:20]), pid)
        return pid, "hold"
    state.upsert_video(pid, status="scripted")
    render(pid)
    make(pid)
    rep = decide(pid, art["text"], fact_rep)
    mark_done(topic["title"], pid, rep["decision"])
    return pid, rep["decision"]


def publish(pid, private_first=False):
    """Upload (idempotent), verify on the channel, record the real status. Returns verification dict."""
    from . import youtube
    cfg = load_config()
    target = "public" if cfg["allow_public_publish"] and cfg["default_privacy"] == "public" else cfg["default_privacy"]
    first = "private" if private_first else target
    vid = youtube.upload(pid, privacy=first, autonomous=True)
    ver = youtube.verify(vid, expect_privacy=first)
    log.info("[%s] verify (%s): %s", pid, first, ver)
    if ver.get("ok") and private_first and target != first:
        youtube.set_privacy(vid, target)
        ver = youtube.verify(vid, expect_privacy=target, wait_s=120)
        log.info("[%s] verify (%s): %s", pid, target, ver)
    status = ver.get("privacyStatus") if ver.get("ok") else "upload_problem"
    state.upsert_video(pid, status="published" if status == "public" else ("uploaded" if ver.get("ok") else "error"),
                       youtube_id=vid, url=f"https://www.youtube.com/watch?v={vid}", privacy=ver.get("privacyStatus"),
                       verified=ver, published_at=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    if not ver.get("ok"):
        notify.alert(f"Upload verification failed: {pid}", json.dumps(ver, indent=1), pid)
    return ver


def _clean_streak():
    """Consecutive successful public publishes of autonomous videos (holds reset the streak)."""
    n = 0
    for r in reversed(_runs()):
        if r.get("kind") != "auto":
            continue
        if r.get("result") == "published":
            n += 1
        elif r.get("result") in ("hold", "error"):
            break
    return n


def quota_today():
    cfg = load_config()
    streak = _clean_streak()
    shorts = 1
    for ph in cfg["ramp"]:
        if streak >= ph["after_clean"]:
            shorts = ph["shorts"]
    longs = 0
    today = datetime.date.today()
    if cfg.get("longs_enabled") or streak >= 7:
        clean_longs = sum(1 for r in _runs() if r.get("format") == "long" and r.get("result") == "published")
        per_week = cfg["longs_per_week"][1] if clean_longs >= 4 else cfg["longs_per_week"][0]
        long_days = {1: [3], 2: [1, 4]}[per_week]          # Thu, or Tue+Fri
        if today.weekday() in long_days:
            longs = 1
    return shorts, longs, streak


def daily():
    from .topics import candidates
    cfg = load_config()
    if not cfg["production_enabled"]:
        log.info("production disabled")
        return
    shorts, longs, streak = quota_today()
    done_today = sum(1 for r in _runs() if r.get("date") == str(datetime.date.today()) and r.get("result") == "published"
                     and r.get("format") == "short")
    shorts = max(0, shorts - done_today)
    log.info("quota today: %d shorts, %d long (clean streak %d)", shorts, longs, streak)
    plan = [("short", shorts), ("long", longs)]
    for fmt, n in plan:
        made, tries = 0, 0
        pool = candidates(n * 3 + 2)
        while made < n and tries < n * 3 and pool:
            topic = pool.pop(0)
            tries += 1
            entry = {"date": str(datetime.date.today()), "topic": topic["title"], "format": fmt, "kind": "auto"}
            try:
                pid, decision = produce(topic, fmt)
                entry.update(id=pid, decision=decision)
                if decision == "publish":
                    ver = publish(pid)
                    entry["result"] = "published" if ver.get("ok") and ver.get("privacyStatus") == "public" else (
                        "uploaded" if ver.get("ok") else "error")
                    entry["url"] = ver.get("url")
                    made += 1 if ver.get("ok") else 0
                elif decision == "hold":
                    entry["result"] = "hold"
                    aq = PROJECTS / pid / "autoqa.json"
                    if aq.exists():
                        notify.alert(f"Held by QA: {topic['title']}", "\n".join(
                            "- " + x for x in json.loads(aq.read_text(encoding="utf-8"))["essential_failures"]), pid)
                else:
                    entry["result"] = "skip"
            except Exception as e:
                import traceback
                entry["result"] = "error"
                entry["error"] = str(e)[:300]
                state.add_error(topic["title"], traceback.format_exc())
                from .youtube import AuthError
                if isinstance(e, AuthError):
                    notify.alert("YouTube authorisation problem – publishing stopped", str(e))
                    _log_run(entry)
                    raise
            _log_run(entry)
            _cleanup()


def publish_existing(pid):
    """Render a reviewed spec (e.g. Doggerland), run QA, upload private, verify, then make public."""
    from .render import render
    from .thumbnail import make
    from .autoqa import decide
    entry = {"date": str(datetime.date.today()), "topic": pid, "format": "short", "kind": "manual-spec", "id": pid}
    render(pid)
    make(pid)
    rep = decide(pid)
    entry["decision"] = rep["decision"]
    if rep["decision"] != "publish":
        entry["result"] = "hold"
        notify.alert(f"Held by QA: {pid}", "\n".join("- " + x for x in rep["essential_failures"]), pid)
        _log_run(entry)
        return rep
    ver = publish(pid, private_first=True)
    entry["result"] = "published" if ver.get("ok") and ver.get("privacyStatus") == "public" else "error"
    entry["url"] = ver.get("url")
    _log_run(entry)
    return ver


def _cleanup():
    """Keep the runner disk small: delete media/work folders of finished projects."""
    for p in PROJECTS.iterdir():
        for sub in ("media", "work"):
            d = p / sub
            if d.exists() and (p / "autoqa.json").exists():
                shutil.rmtree(d, ignore_errors=True)


def dry_run(n=1):
    """Produce n shorts end-to-end (research -> render -> strict QA) WITHOUT publishing.
    Topics are released again afterwards so the real schedule can still use them."""
    from .topics import candidates, HISTORY_FILE, done
    before = done()
    results = []
    for topic in candidates(n + 3):
        if len(results) >= n:
            break
        try:
            pid, decision = produce(topic, "short")
        except Exception as e:
            import traceback
            state.add_error(topic["title"], traceback.format_exc())
            results.append({"topic": topic["title"], "error": str(e)[:300]})
            continue
        if decision == "skip":
            continue
        results.append({"topic": topic["title"], "id": pid, "decision": decision})
    HISTORY_FILE.write_text(json.dumps(before, indent=1, ensure_ascii=False), encoding="utf-8")
    _log_run({"date": str(datetime.date.today()), "kind": "dry-run", "results": results})
    log.info("dry run: %s", results)
    return results


def private_test(pid):
    """Render + strict QA + upload as PRIVATE + verify on the channel. Never switches to public."""
    from .render import render
    from .thumbnail import make
    from .autoqa import decide
    from . import youtube
    render(pid)
    make(pid)
    rep = decide(pid)
    entry = {"date": str(datetime.date.today()), "topic": pid, "format": "short", "kind": "private-test", "id": pid,
             "decision": rep["decision"]}
    if rep["decision"] != "publish":
        entry["result"] = "hold"
        entry["failures"] = rep["essential_failures"][:10]
        _log_run(entry)
        notify.alert(f"Private test held by QA: {pid}", "\n".join("- " + x for x in rep["essential_failures"]), pid)
        return entry
    vid = youtube.upload(pid, privacy="private", autonomous=True)
    ver = youtube.verify(vid, expect_privacy="private")
    state.upsert_video(pid, youtube_id=vid, url=f"https://www.youtube.com/watch?v={vid}",
                       privacy=ver.get("privacyStatus"), verified=ver, status="uploaded-private-test")
    entry.update(result="private-ok" if ver.get("ok") else "error", url=ver.get("url") or f"https://youtu.be/{vid}",
                 verify=ver)
    _log_run(entry)
    log.info("private test: %s", entry)
    return entry
