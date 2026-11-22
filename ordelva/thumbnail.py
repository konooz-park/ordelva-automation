"""1280x720 thumbnail (long videos) + 1080x1920 cover frame (shorts), drawn from the same scene engine."""
import json
from PIL import Image
from .config import PROJECTS
from .visuals.base import Overlay, font, finish


def make(pid):
    from .render import make_scene
    pdir = PROJECTS / pid
    spec = json.loads((pdir / "spec.json").read_text(encoding="utf-8"))
    th = spec.get("thumbnail", {})
    scene = th.get("scene")
    if not scene:
        cands = [b["scene"] for b in spec["beats"] if b["scene"]["type"] in ("image", "map", "map_pin")]
        scene = cands[min(1, len(cands) - 1)] if cands else {"type": "landscape", "mood": "dusk"}
    scene = dict(scene, title=None, labels=[], note=False, gauge=False, label=None, credit=None, disclaimer="")
    lines = th.get("lines") or [spec["title"].upper()]
    out = []
    for (w, h, name) in [(1280, 720, "thumbnail.jpg"), (1080, 1920, "cover.jpg")]:
        s = make_scene(w, h, scene)
        f = s.frame(3.0, 4.0, 0) * 0.8
        ov = Overlay(w, h)
        sc = min(w, h) / 720
        size = int((92 if w > h else 104) * sc)
        y = h * (0.30 if w > h else 0.28)
        for k, ln in enumerate(lines[:3]):
            col = (245, 200, 69) if k == len(lines[:3]) - 1 else (255, 255, 255)
            ov.text((w / 2, y + k * size * 1.1), ln, font("Anton", size), fill=col, stroke=int(5 * sc))
        ov.tracked((w / 2, h - 50 * sc), "ORDELVA", font("Cinzel", int(30 * sc), "Bold"), tracking=0.3, alpha=0.9)
        f = ov.apply(f)
        Image.fromarray(finish(f, 0, vig=0.55, grain_amt=0.0)).save(pdir / name, quality=92)
        out.append(pdir / name)
    return out
