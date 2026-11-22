"""Strict automatic publish gate used in autonomous mode.

decision = "publish"  only if every essential check passes
           "hold"     anything doubtful -> not published, alert issue opened for a human
"""
import json
import re
import statistics
import subprocess
from .config import PROJECTS, STATE_DIR
from . import qa, state
from .state import log

ALLOWED_LICENCES = re.compile(r"(public domain|^pd|cc0|cc by(-sa)?|cc-by|pexels license|owned by channel|apache-2\.0|"
                              r"sil open font|mit)", re.I)
BANNED_TITLE = re.compile(r"\b(shocking|you won'?t believe|proof|100% ?true|aliens?|conspiracy|insane|gone wrong|"
                          r"exposed|they don'?t want you)\b", re.I)
SENSITIVE = re.compile(r"\b(suicide|self-harm|massacre footage|gore|cure for|vaccine|election|terroris\w+)\b", re.I)
SCRIPTS_DIR = STATE_DIR / "scripts"


def _ngrams(text, n=5):
    w = re.findall(r"[a-z']+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def duplicate_check(pid, narration, title):
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    mine = _ngrams(narration)
    worst = (0.0, None)
    for f in SCRIPTS_DIR.glob("*.txt"):
        if f.stem == pid:
            continue
        other = _ngrams(f.read_text(encoding="utf-8"))
        if mine and other:
            j = len(mine & other) / len(mine | other)
            worst = max(worst, (j, f.stem))
    from .topics import too_similar
    titles = [v.get("title", "") for k, v in state.get()["videos"].items() if k != pid and v.get("youtube_id")]
    return {"max_jaccard": round(worst[0], 3), "closest": worst[1], "title_dup": too_similar(title, titles, 0.9)}


def picture_checks(path, dur):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf",
                          "freezedetect=n=0.001:d=6", "-map", "0:v", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    freezes = re.findall(r"freeze_duration: ([\d.]+)", err)
    return {"long_freezes": [float(x) for x in freezes]}


def whisper_checks(pid, timeline, wav, spoken):
    from .align import transcribe, script_match_ratio, _norm
    asr = transcribe(wav)
    script_words = [w for b in timeline for w in b["words"]]
    ratio = script_match_ratio(spoken, asr)
    # caption sync: compare caption word starts with ASR word starts for matching words
    import difflib
    a = [_norm(w[0]) for w in script_words]
    b = [_norm(w[0]) for w in asr]
    offs = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            offs += [abs(script_words[i1 + k][1] - asr[j1 + k][1]) for k in range(i2 - i1)]
    return {"transcript_match": round(ratio, 3),
            "sync_median_s": round(statistics.median(offs), 3) if offs else None,
            "sync_p90_s": round(sorted(offs)[int(len(offs) * 0.9)], 3) if offs else None}


def decide(pid, source_text=None, fact_report=None):
    pdir = PROJECTS / pid
    spec = json.loads((pdir / "spec.json").read_text(encoding="utf-8"))
    tech = qa.auto_checks(pid)
    essential, warnings = [], []
    for c in tech["checks"]:
        if not c["ok"]:
            essential.append(f"technical: {c['check']} – {c['detail']}")
    # facts
    if spec.get("verified") == "manual":
        facts = {"ok": True, "problems": [], "note": "manually verified script"}
    else:
        facts = fact_report or {"ok": False, "problems": ["fact check missing"]}
    if not facts["ok"]:
        essential += [f"facts: {p}" for p in facts["problems"]]
    # audio intelligibility + caption sync (Whisper)
    timeline = json.loads((pdir / "work" / "timeline.json").read_text(encoding="utf-8"))
    try:
        wq = whisper_checks(pid, timeline, str(pdir / "work" / "voice.wav"),
                            " ".join(b.get("say", b["text"]) for b in spec["beats"]))
        if wq["transcript_match"] < 0.90:
            essential.append(f"audio: narration transcript matches script only {wq['transcript_match']:.0%}")
        if wq["sync_median_s"] is None or wq["sync_median_s"] > 0.25 or wq["sync_p90_s"] is None or wq["sync_p90_s"] > 0.7:
            essential.append(f"captions: out of sync (median {wq['sync_median_s']}s, p90 {wq['sync_p90_s']}s)")
    except Exception as e:
        wq = {"error": str(e)}
        essential.append(f"audio/captions: Whisper check could not run ({e})")
    # picture
    meta = json.loads((pdir / "render.json").read_text(encoding="utf-8"))
    pic = picture_checks(meta["output"], tech["duration"])
    if pic["long_freezes"]:
        essential.append(f"picture: frozen image for {max(pic['long_freezes']):.1f}s")
    # licences
    for a in spec.get("assets", []):
        if not ALLOWED_LICENCES.search(a.get("licence", "")):
            essential.append(f"licence not allowed: {a.get('what')} – {a.get('licence')}")
    # duplicates
    narration = " ".join(b["text"] for b in spec["beats"])
    dup = duplicate_check(pid, narration, spec["youtube"]["title"])
    if dup["max_jaccard"] > 0.20 or dup["title_dup"]:
        essential.append(f"duplicate: too similar to {dup['closest']} (jaccard {dup['max_jaccard']}) or same title")
    # metadata + policy
    y = spec["youtube"]
    t = y.get("title", "")
    if not (10 <= len(t) <= 100) or "<" in t or ">" in t:
        essential.append("metadata: title length/characters invalid")
    if BANNED_TITLE.search(t) or BANNED_TITLE.search(y.get("description", "")):
        essential.append("metadata: clickbait / sensational wording")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        essential.append("metadata: title mostly capitals")
    if "http" not in y.get("description", "") or "Sources" not in y.get("description", ""):
        essential.append("metadata: description must list sources")
    if len(",".join(y.get("tags", []))) > 450:
        warnings.append("tags trimmed")
        y["tags"] = y["tags"][:10]
    if not y.get("contains_synthetic_media", True):
        essential.append("policy: AI narration must be disclosed")
    if SENSITIVE.search(narration + " " + t):
        essential.append("policy: sensitive subject – human review required")
    decision = "publish" if not essential else "hold"
    rep = {"decision": decision, "essential_failures": essential, "warnings": warnings, "technical": tech,
           "facts": facts, "whisper": wq, "picture": pic, "duplicate": dup}
    (pdir / "autoqa.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    if decision == "publish":
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        (SCRIPTS_DIR / f"{pid}.txt").write_text(narration, encoding="utf-8")
    state.upsert_video(pid, status="qa_passed" if decision == "publish" else "held", qa_failures=essential[:10])
    log.info("[%s] autoqa decision: %s %s", pid, decision, essential[:5])
    return rep
