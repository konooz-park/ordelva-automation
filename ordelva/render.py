"""Spec (projects/<id>/spec.json) -> finished MP4 with narration, music, captions."""
import json
import os
import subprocess
import time
import numpy as np
from PIL import Image

from .config import FORMATS, FONTS, PROJECTS, OUTPUT, load_config
from . import state
from .state import log
from .tts import narrate_beats
from .captions import build_ass, build_srt
from .audio import compose, mix
from .visuals.base import finish
from .visuals.maps import MapScene, MapPin
from .visuals.procedural import Landscape, Camp, Seabed, TitleCard, ImageScene

SCENES = {"map": MapScene, "map_pin": MapPin, "landscape": Landscape, "camp": Camp, "seabed": Seabed, "image": ImageScene}
XFADE = 0.40


def make_scene(w, h, p):
    if p["type"] == "title":
        bg = make_scene(w, h, p["bg"]) if p.get("bg") else None
        return TitleCard(w, h, p, bg)
    return SCENES[p["type"]](w, h, p)


def load_spec(pid):
    d = PROJECTS / pid
    return d, json.loads((d / "spec.json").read_text(encoding="utf-8"))


def render(pid, preview=False):
    cfg = load_config()
    pdir, spec = load_spec(pid)
    fmt = FORMATS[spec.get("format", "short")]
    W, H, FPS = fmt["w"], fmt["h"], fmt["fps"]
    if preview:
        W, H = W // 2, H // 2
    work = pdir / "work"
    work.mkdir(exist_ok=True)
    state.upsert_video(pid, title=spec["title"], format=spec.get("format"), status="rendering")
    t_start = time.time()
    try:
        # 1. narration
        log.info("[%s] narration (Kokoro, voice=%s)", pid, spec.get("voice", cfg["voice"]))
        voice_wav = str(work / "voice.wav")
        timeline, total = narrate_beats(spec["beats"], voice_wav, voice=spec.get("voice", cfg["voice"]),
                                        lang=spec.get("voice_lang", cfg["voice_lang"]),
                                        speed=spec.get("speed", cfg["voice_speed"]),
                                        tail=spec.get("tail", 1.2))
        # optional whisper refinement + transcript check
        whisper_ratio = None
        if spec.get("whisper", True):
            try:
                from .align import refine_with_whisper
                spoken = " ".join(b.get("say", b["text"]) for b in spec["beats"])
                timeline, whisper_ratio = refine_with_whisper(timeline, voice_wav, log, spoken)
            except Exception as e:
                log.warning("whisper unavailable: %s", e)
        (work / "timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
        log.info("[%s] narration %.1fs, %d beats", pid, total, len(timeline))

        # 2. captions
        ass = work / "captions.ass"
        build_ass(timeline, ass, W, H, spec.get("format", "short"))
        build_srt(timeline, work / "captions.srt")

        # 3. music + sfx cues
        bounds = [0.0] + [b["end"] for b in timeline]
        cues = []
        for i, beat in enumerate(spec["beats"]):
            for s in beat.get("sfx", []):
                cues.append({"t": bounds[i] if s != "impact" else bounds[i] + beat.get("impact_at", 0.6), "kind": s})
            if beat.get("music"):
                cues.append({"t": bounds[i], "kind": beat["music"]})
        music_wav = str(work / "music.wav")
        m = spec.get("music", {})
        compose(total, cues, music_wav, mood=m.get("mood", "mystery"), seed=m.get("seed", 7))
        final_wav = str(work / "mix.wav")
        mix(voice_wav, music_wav, final_wav, cfg["target_lufs"], m.get("db", cfg["music_db"]))

        # 4. video frames -> ffmpeg (captions burned in, audio muxed)
        scenes = [make_scene(W, H, b["scene"]) for b in spec["beats"]]
        out_name = f"{pid}{'_preview' if preview else ''}.mp4"
        out = OUTPUT / out_name
        fonts_rel = os.path.relpath(FONTS, work).replace("\\", "/")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", "mix.wav",
               "-vf", f"ass=captions.ass:fontsdir={fonts_rel}",
               "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "fast" if preview else "medium", "-crf", "26" if preview else "19",
               "-maxrate", "14M" if H * W >= 1920 * 1080 else "6M", "-bufsize", "28M",
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(FPS), "-g", str(FPS * 2),
               "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-t", f"{int(total * FPS) / FPS:.3f}", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(work))
        nframes = int(total * FPS)
        thumbs = {}
        for n in range(nframes):
            T = n / FPS
            i = max(0, min(len(scenes) - 1, int(np.searchsorted(bounds, T, side="right")) - 1))
            t_local = T - bounds[i]
            dur = bounds[i + 1] - bounds[i]
            f = scenes[i].frame(t_local, dur, n)
            # crossfade into the next beat
            if i + 1 < len(scenes) and bounds[i + 1] - T < XFADE / 2:
                a = (XFADE / 2 - (bounds[i + 1] - T)) / XFADE
                g = scenes[i + 1].frame(0.0, bounds[i + 2] - bounds[i + 1], n)
                f = f * (1 - a) + g * a
            elif i > 0 and t_local < XFADE / 2:
                a = 0.5 + t_local / XFADE
                g = scenes[i - 1].frame(bounds[i] - bounds[i - 1] + t_local, bounds[i] - bounds[i - 1], n)
                f = g * (1 - a) + f * a
            # fade from/to black
            if T < 0.25:
                f = f * (T / 0.25)
            if total - T < 0.6:
                f = f * max(0.0, (total - T) / 0.6)
            px = finish(f, n, vig=0.45, grain_amt=0.007)
            try:
                proc.stdin.write(px.tobytes())
            except BrokenPipeError:
                raise RuntimeError("ffmpeg stopped early – see the ffmpeg message above")
            if n % (FPS * 5) == 0:
                log.info("[%s] frame %d/%d", pid, n, nframes)
            if i not in thumbs and t_local > dur * 0.6:
                thumbs[i] = px
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg encode failed")
        # contact sheet for human review
        sheet_imgs = [Image.fromarray(thumbs[k]) for k in sorted(thumbs)]
        if sheet_imgs:
            tw = 270 if H > W else 480
            th = int(tw * H / W)
            cols = 6
            rows = (len(sheet_imgs) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * tw, rows * th))
            for k, im in enumerate(sheet_imgs):
                sheet.paste(im.resize((tw, th)), ((k % cols) * tw, (k // cols) * th))
            sheet.save(pdir / "contact_sheet.jpg", quality=88)
        meta = {"seconds": round(total, 2), "render_seconds": round(time.time() - t_start, 1),
                "whisper_match": whisper_ratio, "output": str(out)}
        (pdir / "render.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        state.upsert_video(pid, status="rendered", file=str(out), seconds=meta["seconds"])
        log.info("[%s] done -> %s (%.0fs render)", pid, out, meta["render_seconds"])
        return out
    except Exception as e:
        import traceback
        state.upsert_video(pid, status="error")
        state.add_error(pid, f"{e}\n{traceback.format_exc()}")
        raise
