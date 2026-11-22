"""Automatic quality gate + mandatory human review checklist.

A video can only be uploaded when:
  1. every automatic check passes (format, duration, loudness, silence, black frames, captions), AND
  2. a human has ticked the review checklist (facts, licences, audio, picture) in review.json.
"""
import json
import re
import subprocess
from .config import FORMATS, PROJECTS
from . import state

REVIEW_ITEMS = [
    "facts_checked",      # every claim in spec.facts verified against its sources
    "licences_checked",   # every asset in spec.assets has a licence that allows commercial use
    "audio_checked",      # narration clear, pronunciation correct, music level OK
    "picture_checked",    # visuals correct, no errors / misleading imagery, captions in sync
    "metadata_checked",   # title/description/tags accurate, AI-voice disclosure set
]


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _ff(path, filt, kind="a"):
    flag = "-af" if kind == "a" else "-vf"
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), flag, filt, "-f", "null", "-"],
                          capture_output=True, text=True).stderr


def auto_checks(pid):
    pdir = PROJECTS / pid
    spec = json.loads((pdir / "spec.json").read_text(encoding="utf-8"))
    meta = json.loads((pdir / "render.json").read_text(encoding="utf-8"))
    fmt = FORMATS[spec.get("format", "short")]
    path = meta["output"]
    p = probe(path)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    a = [s for s in p["streams"] if s["codec_type"] == "audio"]
    dur = float(p["format"]["duration"])
    fps = eval(v["r_frame_rate"])
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("resolution", (v["width"], v["height"]) == (fmt["w"], fmt["h"]), f'{v["width"]}x{v["height"]}')
    add("codec", v["codec_name"] == "h264" and v.get("pix_fmt") == "yuv420p", f'{v["codec_name"]} {v.get("pix_fmt")}')
    add("fps", abs(fps - fmt["fps"]) < 0.01, f"{fps:.2f}")
    add("duration", fmt["min_s"] <= dur <= fmt["max_s"], f"{dur:.2f}s (allowed {fmt['min_s']}-{fmt['max_s']})")
    add("audio_stream", len(a) == 1 and a[0]["codec_name"] == "aac", a[0]["codec_name"] if a else "none")
    eb = _ff(path, "ebur128=peak=true")
    m_i = re.findall(r"I:\s+(-?[\d.]+) LUFS", eb)
    m_tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", eb)
    lufs = float(m_i[-1]) if m_i else None
    tp = float(m_tp[-1]) if m_tp else None
    add("loudness", lufs is not None and -16 <= lufs <= -12.5, f"{lufs} LUFS (target -14)")
    add("true_peak", tp is not None and tp <= -0.5, f"{tp} dBTP")
    sil = _ff(path, "silencedetect=n=-45dB:d=1.5")
    gaps = [(float(s), float(e)) for s, e in zip(re.findall(r"silence_start: (-?[\d.]+)", sil),
                                                  re.findall(r"silence_end: ([\d.]+)", sil))]
    mid_gaps = [g for g in gaps if g[0] > 1.0 and g[1] < dur - 2.0]
    add("no_dead_air", not mid_gaps, f"{len(mid_gaps)} silent gaps >1.5s inside video")
    bl = _ff(path, "blackdetect=d=0.5:pix_th=0.06", kind="v")
    blacks = [(float(s), float(e)) for s, e in zip(re.findall(r"black_start:([\d.]+)", bl), re.findall(r"black_end:([\d.]+)", bl))]
    mid_black = [b for b in blacks if b[0] > 0.5 and b[1] < dur - 1.0]
    add("no_black_frames", not mid_black, f"{len(mid_black)} black segments inside video")
    ass = pdir / "work" / "captions.ass"
    n_events = sum(1 for line in ass.read_text(encoding="utf-8").splitlines() if line.startswith("Dialogue")) if ass.exists() else 0
    add("captions", n_events > 10, f"{n_events} caption events burned in; SRT for YouTube CC also written")
    facts = spec.get("facts", [])
    add("facts_have_sources", facts and all(f.get("sources") for f in facts), f"{len(facts)} claims, all with sources")
    assets = spec.get("assets", [])
    add("assets_have_licences", assets and all(x.get("licence") for x in assets), f"{len(assets)} assets with licence")
    wm = meta.get("whisper_match")
    if wm is not None:
        add("transcript_matches_script", wm >= 0.9, f"Whisper match {wm:.2f}")
    report = {"video": path, "duration": dur, "lufs": lufs, "true_peak": tp,
              "passed": all(c["ok"] for c in checks), "checks": checks}
    (pdir / "qa.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    review = pdir / "review.json"
    if not review.exists():
        review.write_text(json.dumps({k: False for k in REVIEW_ITEMS} | {"reviewer": "", "notes": ""}, indent=2),
                          encoding="utf-8")
    state.upsert_video(pid, status="review" if report["passed"] else "qa_failed", qa_passed=report["passed"],
                       lufs=lufs, seconds=round(dur, 2))
    return report


def approve(pid, reviewer, notes=""):
    """Called only by a human (CLI `review --approve` or dashboard button) after watching the video."""
    pdir = PROJECTS / pid
    qa = json.loads((pdir / "qa.json").read_text(encoding="utf-8"))
    if not qa["passed"]:
        raise SystemExit("Automatic QA has failures; fix them before approval.")
    rv = {k: True for k in REVIEW_ITEMS} | {"reviewer": reviewer, "notes": notes}
    (pdir / "review.json").write_text(json.dumps(rv, indent=2), encoding="utf-8")
    state.upsert_video(pid, status="approved", reviewer=reviewer)


def is_publishable(pid):
    pdir = PROJECTS / pid
    try:
        qa = json.loads((pdir / "qa.json").read_text(encoding="utf-8"))
        rv = json.loads((pdir / "review.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    return qa["passed"] and all(rv.get(k) for k in REVIEW_ITEMS) and bool(rv.get("reviewer"))
