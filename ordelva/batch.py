"""Daily production run (Task Scheduler calls `ordelva.bat batch`).

Produces drafts -> renders -> QA, and stops at the human review gate.
It never publishes on its own: only videos already approved by a human are uploaded (private/scheduled).
Disabled until the owner sets "production_enabled": true in config.json.
"""
import datetime
import re
from .config import load_config
from . import state
from .state import log


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def run():
    cfg = load_config()
    if not cfg["production_enabled"]:
        log.info("batch: production_enabled=false -> nothing to do (enable after quality sign-off)")
        return
    from .llm import fetch_research, draft_spec
    from .stock import fetch_for_spec
    from .render import render
    from .qa import auto_checks, is_publishable
    from .thumbnail import make
    s = state.get()
    ideas = [i for i in s.get("ideas", []) if i.get("status") == "idea"]
    today = datetime.date.today()
    want_long = today.weekday() in (1, 4) and cfg["weekly_longs"] > 0      # Tue + Fri
    todo = [i for i in ideas if i.get("format") == "short"][: cfg["daily_shorts"]]
    if want_long:
        todo += [i for i in ideas if i.get("format") == "long"][:1]
    for idea in todo:
        pid = f'{today:%Y%m%d}-{_slug(idea["title"])}'
        try:
            notes, sources = fetch_research(idea["wikipedia_title"])
            draft_spec(pid, idea["title"], notes, sources, idea.get("format", "short"))
            fetch_for_spec(pid)
            render(pid)
            make(pid)
            auto_checks(pid)
            idea["status"] = "produced"
        except Exception as e:
            state.add_error(pid, f"batch failed: {e}")
            idea["status"] = "failed"
    with state._lock:
        st = state._read()
        st["ideas"] = s.get("ideas", [])
        state._write(st)
    # upload only human-approved videos, as private (or scheduled) uploads
    if cfg.get("auto_upload_approved"):
        from .youtube import upload
        for pid, v in state.get()["videos"].items():
            if v.get("status") == "approved" and is_publishable(pid):
                try:
                    upload(pid)
                except Exception as e:
                    state.add_error(pid, f"upload failed: {e}")
