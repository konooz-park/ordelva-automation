"""Tiny JSON-backed state store + operation log used by the CLI and dashboard."""
import json
import logging
import threading
import time
from .config import STATE_FILE, LOGS

_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOGS / "ordelva.log", encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("ordelva")

STATUSES = ["idea", "scripted", "rendering", "rendered", "qa_failed", "review", "approved",
            "queued", "uploaded", "published", "error"]


def _read():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"videos": {}, "errors": [], "channel": {}}


def _write(s):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def get():
    with _lock:
        return _read()


def upsert_video(vid: str, **fields):
    with _lock:
        s = _read()
        v = s["videos"].setdefault(vid, {"id": vid, "created": time.strftime("%Y-%m-%d %H:%M")})
        v.update(fields)
        v["updated"] = time.strftime("%Y-%m-%d %H:%M")
        _write(s)
        return v


def add_error(vid: str, msg: str):
    log.error("%s: %s", vid, msg)
    with _lock:
        s = _read()
        s["errors"].append({"video": vid, "msg": msg[:2000], "at": time.strftime("%Y-%m-%d %H:%M")})
        s["errors"] = s["errors"][-200:]
        _write(s)


def set_channel(stats: dict):
    with _lock:
        s = _read()
        s["channel"] = stats
        _write(s)
