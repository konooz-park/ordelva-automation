"""Weekly report: what was published, what worked, what failed, corrective actions."""
import datetime
import json
from .config import ROOT
from . import state, notify
from .pipeline import _runs, quota_today


def weekly():
    try:
        from .youtube import refresh_stats
        refresh_stats()
    except Exception as e:
        stats_err = str(e)
    else:
        stats_err = None
    s = state.get()
    today = datetime.date.today()
    since = today - datetime.timedelta(days=7)
    runs = [r for r in _runs() if r.get("date", "") >= str(since)]
    pub = [r for r in runs if r.get("result") == "published"]
    held = [r for r in runs if r.get("result") == "hold"]
    err = [r for r in runs if r.get("result") == "error"]
    vids = [v for v in s["videos"].values() if v.get("youtube_id")]
    vids.sort(key=lambda v: v.get("views", 0), reverse=True)
    ch = s.get("channel", {})
    shorts, longs, streak = quota_today()
    lines = [f"## ORDELVA weekly report – {since} to {today}", "",
             f"**Channel:** {ch.get('title', '?')} · subscribers {ch.get('subscriberCount', '?')} · total views {ch.get('viewCount', '?')}",
             f"**This week:** {len(pub)} published · {len(held)} held by QA · {len(err)} errors · clean streak {streak} → "
             f"current quota {shorts} short(s)/day" + (", long video this week" if longs else ""), ""]
    lines.append("### Published")
    for r in pub:
        v = s["videos"].get(r.get("id"), {})
        lines.append(f"- [{r['topic']}]({r.get('url')}) – {v.get('views', 0)} views, avg viewed {v.get('avg_view_pct', '–')}%")
    if not pub:
        lines.append("- none")
    lines += ["", "### Best performers (all time)"]
    for v in vids[:5]:
        lines.append(f"- {v.get('title')} – {v.get('views', 0)} views, {v.get('avg_view_pct', '–')}% viewed, +{v.get('subs_gained', 0)} subs")
    lines += ["", "### Held / failed (not published)"]
    for r in held + err:
        v = s["videos"].get(r.get("id"), {})
        lines.append(f"- {r['topic']}: {r.get('result')} – {'; '.join(v.get('qa_failures', [])[:3]) or r.get('error', '')}")
    if not (held or err):
        lines.append("- none")
    lines += ["", "### Corrective actions (automatic)"]
    from .topics import pillar_weights
    w = pillar_weights()
    lines.append("- Topic weights from audience retention/views: " + ", ".join(f"{k} ×{v:.2f}" for k, v in w.items()))
    if held:
        lines.append("- Held videos stay unpublished; review them in the linked alert issues.")
    if stats_err:
        lines.append(f"- Analytics could not be read: {stats_err[:200]}")
    body = "\n".join(lines)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / f"{today:%Y-%m-%d}.md").write_text(body, encoding="utf-8")
    notify.issue(f"ORDELVA weekly report {today:%Y-%m-%d}", body, ["ordelva-report"])
    return body
