"""ORDELVA command line.  Windows: use  ordelva.bat <command>

  check                      test every component (ffmpeg, Kokoro, Whisper, Ollama, YouTube token)
  ideas [--n 10]             generate topic ideas with the local LLM (Ollama)
  draft <id> <wiki_title> [--format short|long] [--title "..."]
                             research (Wikipedia) + grounded script draft -> projects/<id>/spec.json
  media <id>                 fetch licensed images for `image` scenes (Pexels / Wikimedia Commons)
  render <id> [--preview]    narration + music + visuals + captions -> output/<id>.mp4
  qa <id>                    automatic quality checks -> projects/<id>/qa.json
  approve <id> --reviewer NAME   human sign-off (facts, licences, audio, picture, metadata)
  auth                       connect the ORDELVA YouTube channel (official OAuth in your browser)
  upload <id> [--privacy private|unlisted|public] [--publish-at ISO]
  stats                      refresh channel + video statistics
  batch                      daily run (only when production_enabled=true in config.json)
  dashboard [--port 8765]    local control panel
"""
import argparse
import json
import shutil
import subprocess
import sys
import time


def cmd_check(_):
    from .config import load_config, SECRETS_DIR
    rows = []

    def row(name, ok, info):
        rows.append((name, ok, info))
        print(f"[{'OK ' if ok else '-- '}] {name:<18} {info}")

    ff = shutil.which("ffmpeg")
    row("ffmpeg", bool(ff), subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0] if ff else "missing")
    try:
        from .tts import _engine
        t = time.time()
        a, sr = _engine().create("ORDELVA system check.", voice=load_config()["voice"], lang="en-gb")
        row("kokoro_tts", len(a) > sr * 0.5, f"{len(a)/sr:.1f}s audio in {time.time()-t:.1f}s")
    except Exception as e:
        row("kokoro_tts", False, str(e)[:120])
    try:
        import faster_whisper  # noqa
        row("faster_whisper", True, "installed (model downloads on first use)")
    except Exception as e:
        row("faster_whisper", False, str(e)[:120])
    try:
        import requests
        cfg = load_config()
        tags = requests.get(cfg["ollama_url"] + "/api/tags", timeout=5).json()
        names = [m["name"] for m in tags.get("models", [])]
        row("ollama", cfg["ollama_model"] in names, f"models: {names}; configured: {cfg['ollama_model']}")
    except Exception:
        row("ollama", False, "not running (optional – scripts can be written by hand)")
    try:
        import onnxruntime as ort
        row("onnx_providers", True, ", ".join(ort.get_available_providers()))
    except Exception as e:
        row("onnx_providers", False, str(e)[:80])
    row("youtube_token", (SECRETS_DIR / "token.json").exists(), str(SECRETS_DIR))
    return all(ok for n, ok, _ in rows if n in ("ffmpeg", "kokoro_tts"))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ordelva", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    p = sub.add_parser("ideas"); p.add_argument("--n", type=int, default=10)
    p = sub.add_parser("draft"); p.add_argument("id"); p.add_argument("wiki_title")
    p.add_argument("--format", default="short"); p.add_argument("--title")
    p = sub.add_parser("media"); p.add_argument("id")
    p = sub.add_parser("render"); p.add_argument("id"); p.add_argument("--preview", action="store_true")
    p = sub.add_parser("qa"); p.add_argument("id")
    p = sub.add_parser("thumbnail"); p.add_argument("id")
    p = sub.add_parser("approve"); p.add_argument("id"); p.add_argument("--reviewer", required=True); p.add_argument("--notes", default="")
    sub.add_parser("auth")
    p = sub.add_parser("upload"); p.add_argument("id"); p.add_argument("--privacy"); p.add_argument("--publish-at")
    sub.add_parser("stats")
    sub.add_parser("batch")
    p = sub.add_parser("dashboard"); p.add_argument("--port", type=int, default=8765)
    p = sub.add_parser("cloud"); p.add_argument("--mode", default="daily"); p.add_argument("--id", default="doggerland-short")
    sub.add_parser("bootstrap")
    a = ap.parse_args(argv)

    if a.cmd == "check":
        sys.exit(0 if cmd_check(a) else 1)
    if a.cmd == "ideas":
        from .llm import ideas
        for i in ideas(a.n):
            print(f"- {i.get('title')}  [{i.get('format')}]  ({i.get('wikipedia_title')})")
    elif a.cmd == "draft":
        from .llm import fetch_research, draft_spec
        notes, sources = fetch_research(a.wiki_title)
        draft_spec(a.id, a.title or a.wiki_title, notes, sources, a.format)
        print(f"Draft written: projects/{a.id}/spec.json  -> review facts, then: ordelva media {a.id} ; ordelva render {a.id}")
    elif a.cmd == "media":
        from .stock import fetch_for_spec
        fetch_for_spec(a.id)
    elif a.cmd == "render":
        from .render import render
        from .thumbnail import make
        out = render(a.id, preview=a.preview)
        make(a.id)
        if not a.preview:
            from .qa import auto_checks
            rep = auto_checks(a.id)
            print(json.dumps({c["check"]: ("PASS " if c["ok"] else "FAIL ") + c["detail"] for c in rep["checks"]}, indent=1))
        print(out)
    elif a.cmd == "qa":
        from .qa import auto_checks
        rep = auto_checks(a.id)
        for c in rep["checks"]:
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']:<26} {c['detail']}")
        sys.exit(0 if rep["passed"] else 1)
    elif a.cmd == "thumbnail":
        from .thumbnail import make
        print(make(a.id))
    elif a.cmd == "approve":
        from .qa import approve
        approve(a.id, a.reviewer, a.notes)
        print("approved")
    elif a.cmd == "auth":
        from .youtube import authorise
        print(authorise())
    elif a.cmd == "upload":
        from .youtube import upload
        print(upload(a.id, a.privacy, a.publish_at))
    elif a.cmd == "stats":
        from .youtube import refresh_stats
        refresh_stats()
    elif a.cmd == "batch":
        from .batch import run
        run()
    elif a.cmd == "bootstrap":
        from .bootstrap import main as bs
        bs()
    elif a.cmd == "cloud":
        from . import pipeline
        if a.mode == "daily":
            pipeline.daily()
        elif a.mode == "publish-existing":
            print(json.dumps(pipeline.publish_existing(a.id), indent=1, default=str))
        elif a.mode == "report":
            from .report import weekly
            print(weekly())
        elif a.mode == "check":
            from .youtube import channel_identity
            ok = cmd_check(a)
            print("channel:", channel_identity())
            sys.exit(0 if ok else 1)
        elif a.mode == "dry-run":
            print(json.dumps(pipeline.dry_run(1), indent=1))
        elif a.mode == "stats":
            from .youtube import refresh_stats
            print(refresh_stats())
        else:
            raise SystemExit(f"unknown mode {a.mode}")
    elif a.cmd == "dashboard":
        from dashboard.server import serve
        serve(a.port)


if __name__ == "__main__":
    main()
