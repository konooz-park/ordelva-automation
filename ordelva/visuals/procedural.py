"""Original, code-generated cinematic scenes (no third-party footage, so no licence risk).
Each scene is labelled on screen as an illustration / artist's impression."""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from .base import Overlay, font, ease, ease_out, lerp


def _fbm(x, seed, octaves=5):
    rng = np.random.default_rng(seed)
    out = np.zeros_like(x, dtype=np.float64)
    amp, freq = 1.0, 1.0
    for _ in range(octaves):
        ph = rng.uniform(0, 2 * np.pi, 3)
        out += amp * (np.sin(x * freq + ph[0]) * 0.6 + np.sin(x * freq * 1.7 + ph[1]) * 0.4)
        amp *= 0.5
        freq *= 2.1
    return out


def _sky(w, h, top, mid, horizon, hy):
    y = np.linspace(0, 1, h)[:, None]
    hyf = hy / h
    a = np.clip(y / hyf, 0, 1)[..., None]
    col = np.where(a < 0.6, lerp(np.array(top), np.array(mid), a / 0.6), lerp(np.array(mid), np.array(horizon), (a - 0.6) / 0.4))
    return np.broadcast_to(col, (h, w, 3)).astype(np.float32).copy()


def _glow(w, h, cx, cy, radius, color, power=2.0):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / radius
    g = np.exp(-d ** power)
    return g[..., None] * np.array(color, np.float32)


def _ridge_layer(W, h, base_y, amp, freq, seed, color, alpha=1.0):
    xs = np.arange(W)
    ys = base_y - amp * (0.5 + 0.5 * _fbm(xs / W * freq * 2 * np.pi, seed, octaves=3) / 1.6)
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(0, h)] + [(int(x), float(y)) for x, y in zip(xs[::4], ys[::4])] + [(W - 1, float(ys[-1])), (W - 1, h)]
    d.polygon(pts, fill=tuple(int(c * 255) for c in color) + (int(alpha * 255),))
    return img


class Landscape:
    """Dawn/dusk plains with rivers and marsh – parallax layers."""

    def __init__(self, w, h, p):
        self.w, self.h, self.p = w, h, p
        dusk = p.get("mood", "dawn") == "dusk"
        self.dusk = dusk
        self.hy = int(h * ((0.42 if p.get("mood") == "dusk" else 0.50) if h > w else 0.55))
        if dusk:
            sky = _sky(w, h, (0.05, 0.05, 0.14), (0.30, 0.16, 0.30), (0.95, 0.45, 0.22), self.hy)
            sun = _glow(w, h, w * 0.30, self.hy - h * 0.01, w * 0.55, (0.55, 0.22, 0.05), 1.4)
            haze = np.array([0.55, 0.30, 0.30])
        else:
            sky = _sky(w, h, (0.08, 0.13, 0.27), (0.36, 0.38, 0.50), (0.92, 0.62, 0.40), self.hy)
            sun = _glow(w, h, w * 0.64, self.hy - h * 0.03, w * 0.40, (0.45, 0.30, 0.12), 1.3)
            sun += _glow(w, h, w * 0.64, self.hy - h * 0.03, w * 0.04, (0.9, 0.8, 0.6), 2.0)
            haze = np.array([0.75, 0.62, 0.55])
        self.sky = np.clip(sky + sun, 0, 1)
        dark = np.array([0.06, 0.07, 0.06]) if dusk else np.array([0.10, 0.13, 0.09])
        W = int(w * 1.4)
        self.layers = []
        specs = [(0.00, 0.012, 2, 11, 0.06), (0.010, 0.016, 2, 23, 0.14), (0.030, 0.020, 3, 37, 0.25)]
        for k, (off, amp, fq, seed, speed) in enumerate(specs):
            col = lerp(haze, dark, (k + 1) / (len(specs) + 1.5))
            self.layers.append((_ridge_layer(W, h, self.hy + off * h, amp * h, fq, seed, col), speed))
        # foreground plain with meandering river (reflects sky)
        fg = Image.new("RGBA", (W, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(fg)
        gy = int(self.hy + 0.06 * h)
        base = tuple(int(c * 255) for c in lerp(lerp(haze, dark, 0.8), np.array([0.20, 0.25, 0.13]), 0.55)) + (255,)
        d.rectangle((0, gy, W, h), fill=base)
        river_col = tuple(int(c * 255) for c in (np.array([0.95, 0.62, 0.40]) if not dusk else np.array([0.85, 0.40, 0.25])))
        pts_l, pts_r = [], []
        for yy in range(gy, h + 40, 8):
            v = (yy - gy) / (h - gy)
            cx = W * 0.5 + math.sin(v * 5.0 + 0.7) * W * 0.12 * (0.3 + v)
            half = 4 + v ** 1.6 * w * 0.16
            pts_l.append((cx - half, yy))
            pts_r.append((cx + half, yy))
        if p.get("river", True):
            d.polygon(pts_l + pts_r[::-1], fill=river_col + (235,))
        # marsh pools
        rng = np.random.default_rng(5)
        for _ in range(14):
            v = rng.uniform(0.15, 0.9)
            yy = gy + v * (h - gy)
            xx = rng.uniform(0, W)
            rw, rh = (20 + v * 160), (3 + v * 14)
            d.ellipse((xx - rw, yy - rh, xx + rw, yy + rh), fill=river_col + (150,))
        # reeds
        for _ in range(420):
            v = rng.uniform(0.55, 1.0)
            xx = rng.uniform(0, W)
            yy = gy + v * (h - gy)
            ln = 10 + v ** 2 * 120
            d.line((xx, yy, xx + rng.uniform(-6, 6), yy - ln), fill=(8, 10, 8, 255), width=max(1, int(v * 4)))
        self.fg = fg.filter(ImageFilter.GaussianBlur(0.6))
        self.birds = [(rng.uniform(-0.3, 0.2), rng.uniform(0.22, 0.38), rng.uniform(0.7, 1.3)) for _ in range(9)]
        self.mist = _glow(w, h, w / 2, self.hy + 0.02 * h, w * 0.9, (0.35, 0.30, 0.30) if dusk else (0.45, 0.40, 0.38), 6)

    def base(self, t, dur):
        w, h = self.w, self.h
        img = Image.fromarray((self.sky * 255).astype(np.uint8)).convert("RGBA")
        for lay, sp in self.layers:
            x = int((lay.width - w) * (0.15 + sp * t / max(dur, 1)))
            img.alpha_composite(lay.crop((x, 0, x + w, h)))
        x = int((self.fg.width - w) * (0.2 + 0.4 * t / max(dur, 1)))
        img.alpha_composite(self.fg.crop((x, 0, x + w, h)))
        frame = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        frame = frame + self.mist * (0.6 + 0.2 * math.sin(t * 0.7))
        return frame

    def frame(self, t, dur, i):
        w, h = self.w, self.h
        u = t / max(dur, 1e-6)
        frame = self.base(t, dur)
        ov = Overlay(w, h)
        sc = w / 1080 if h > w else h / 1080
        if not self.dusk:
            for bx, by, s in self.birds:
                x = (bx + 0.06 * t * s) * w
                y = by * h + math.sin(t * 2 + bx * 10) * 6
                flap = math.sin(t * 8 * s + bx * 20) * 7 * sc
                ov.line([(x - 16 * sc, y - flap), (x, y), (x + 16 * sc, y - flap)], fill=(25, 20, 30), width=int(3 * sc), alpha=0.9)
        self._extra(ov, t, u, sc)
        lab = self.p.get("label")
        if lab:
            al = ease_out((u - 0.08) / 0.15)
            ty = h * (0.16 if h > w else 0.12)
            ov.tracked((w / 2, ty), lab, font("Montserrat", int(34 * sc), "Bold"), tracking=0.22, alpha=al,
                       fill=(245, 200, 69))
            if self.p.get("sublabel"):
                ov.tracked((w / 2, ty + 52 * sc), self.p["sublabel"], font("Montserrat", int(26 * sc), "SemiBold"),
                           tracking=0.2, alpha=al * 0.9)
        ov.text((w / 2, h * (0.115 if h > w else 0.05)), self.p.get("disclaimer", "ARTIST'S IMPRESSION"),
                font("Montserrat", int(20 * sc), "Medium"), alpha=0.7)
        frame = ov.apply(frame)
        z = lerp(1.0, self.p.get("push", 1.08), ease(u))
        if z > 1.001:
            pil = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))
            cw, ch = w / z, h / z
            pil = pil.resize((w, h), Image.BILINEAR, box=((w - cw) / 2, (h - ch) * 0.55, (w + cw) / 2, (h - ch) * 0.55 + ch))
            frame = np.asarray(pil, dtype=np.float32) / 255.0
        return frame

    def _extra(self, ov, t, u, sc):
        pass


def _person(d, x, y, s, spear=False, crouch=False, color=(6, 5, 6, 255)):
    """Simple silhouette figure, feet at (x, y), height ~ s."""
    hh = s * (0.72 if crouch else 1.0)
    head_r = s * 0.065
    top = y - hh
    d.ellipse((x - head_r, top, x + head_r, top + 2 * head_r), fill=color)
    neck = top + 2 * head_r
    torso_b = neck + hh * 0.40
    d.polygon([(x - s * 0.085, neck + s * 0.02), (x + s * 0.085, neck + s * 0.02), (x + s * 0.07, torso_b), (x - s * 0.07, torso_b)], fill=color)
    # cloak / fur
    d.polygon([(x - s * 0.10, neck + s * 0.03), (x + s * 0.10, neck + s * 0.03), (x + s * 0.12, torso_b + s * 0.05), (x - s * 0.12, torso_b + s * 0.05)], fill=color)
    lw = max(2, int(s * 0.05))
    if crouch:
        d.line((x - s * 0.05, torso_b, x - s * 0.16, y - s * 0.12, x - s * 0.10, y), fill=color, width=lw)
        d.line((x + s * 0.05, torso_b, x + s * 0.14, y - s * 0.14, x + s * 0.18, y), fill=color, width=lw)
    else:
        d.line((x - s * 0.04, torso_b, x - s * 0.09, y), fill=color, width=lw)
        d.line((x + s * 0.04, torso_b, x + s * 0.08, y), fill=color, width=lw)
    if spear:
        d.line((x + s * 0.09, neck + s * 0.10, x + s * 0.20, top - s * 0.25), fill=color, width=max(2, int(s * 0.018)))
        d.line((x + s * 0.20, top - s * 0.25, x + s * 0.18, top - s * 0.38), fill=color, width=max(2, int(s * 0.03)))
        d.line((x + s * 0.06, neck + s * 0.06, x + s * 0.12, neck + s * 0.10), fill=color, width=lw)


class Camp(Landscape):
    """Dusk camp with a fire and hunter-gatherer silhouettes."""

    def __init__(self, w, h, p):
        p = dict(p)
        p["mood"] = "dusk"
        p["river"] = False
        super().__init__(w, h, p)
        gy = self.hy + 0.06 * h
        self.fire = (w * 0.52, gy + (h - gy) * (0.16 if h > w else 0.42))
        s = h * (0.17 if h > w else 0.24)
        self.people = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.people)
        fx, fy = self.fire
        _person(d, fx - w * 0.22, fy + s * 0.15, s, spear=True)
        _person(d, fx + w * 0.17, fy + s * 0.10, s * 0.95, crouch=True)
        _person(d, fx - w * 0.05, fy - s * 0.18, s * 0.72)
        # simple shelter
        d.polygon([(fx + w * 0.26, fy - s * 0.05), (fx + w * 0.36, fy - s * 0.75), (fx + w * 0.46, fy - s * 0.05)], fill=(10, 8, 9, 255))
        self.rng = np.random.default_rng(9)
        self.sparks = [(self.rng.uniform(-1, 1), self.rng.uniform(0, 1), self.rng.uniform(0.6, 1.4)) for _ in range(40)]
        self.glow_big = _glow(w, h, fx, fy, w * 0.35, (1.0, 0.45, 0.12), 1.5)
        self.glow_core = _glow(w, h, fx, fy - s * 0.05, w * 0.06, (1.0, 0.85, 0.45), 2.0)

    def frame(self, t, dur, i):
        w, h = self.w, self.h
        u = t / max(dur, 1e-6)
        frame = self.base(t, dur) * 0.62
        flick = 0.75 + 0.15 * math.sin(t * 13) + 0.1 * math.sin(t * 29 + 1)
        frame = frame + self.glow_big * 0.55 * flick + self.glow_core * flick
        img = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
        img.alpha_composite(self.people)
        d = ImageDraw.Draw(img)
        fx, fy = self.fire
        sc = w / 1080 if h > w else h / 1080
        for k in range(7):  # flames
            ph = t * (6 + k) + k
            fh = (40 + 25 * math.sin(ph)) * sc
            ox = (k - 3) * 9 * sc + math.sin(ph * 1.3) * 5 * sc
            d.polygon([(fx + ox - 12 * sc, fy), (fx + ox + 12 * sc, fy), (fx + ox + math.sin(ph) * 6 * sc, fy - fh)],
                      fill=(255, 170 + k * 10, 60, 210))
        for sx, sy, sp in self.sparks:
            life = (t * 0.5 * sp + sy) % 1.0
            x = fx + sx * 40 * sc + math.sin(life * 9 + sx * 5) * 20 * sc
            y = fy - life * h * 0.28
            a = int(255 * (1 - life))
            d.ellipse((x - 2.5 * sc, y - 2.5 * sc, x + 2.5 * sc, y + 2.5 * sc), fill=(255, 200, 120, a))
        frame = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        ov = Overlay(w, h)
        lab = self.p.get("label")
        if lab:
            al = ease_out((u - 0.08) / 0.15)
            ty = h * (0.16 if h > w else 0.12)
            ov.tracked((w / 2, ty), lab, font("Montserrat", int(34 * sc), "Bold"), tracking=0.22, alpha=al, fill=(245, 200, 69))
            if self.p.get("sublabel"):
                ov.tracked((w / 2, ty + 52 * sc), self.p["sublabel"], font("Montserrat", int(26 * sc), "SemiBold"),
                           tracking=0.2, alpha=al * 0.9)
        ov.text((w / 2, h * (0.115 if h > w else 0.05)), "ARTIST'S IMPRESSION", font("Montserrat", int(20 * sc), "Medium"), alpha=0.7)
        frame = ov.apply(frame)
        z = lerp(1.0, self.p.get("push", 1.10), ease(u))
        pil = Image.fromarray((np.clip(frame, 0, 1) * 255).astype(np.uint8))
        cw, ch = w / z, h / z
        pil = pil.resize((w, h), Image.BILINEAR, box=((w - cw) / 2, (h - ch) * 0.6, (w + cw) / 2, (h - ch) * 0.6 + ch))
        return np.asarray(pil, dtype=np.float32) / 255.0


def _antler_point(length):
    """Barbed antler point sprite (illustration, ~22 cm original). Returns RGBA image."""
    L = int(length)
    H = int(length * 0.16)
    img = Image.new("RGBA", (L + 20, H * 2 + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cy = H + 10
    shaft = [(10, cy - H * 0.22), (L * 0.82, cy - H * 0.12), (L + 8, cy), (L * 0.82, cy + H * 0.14), (10, cy + H * 0.25)]
    bone = (222, 204, 168, 255)
    d.polygon(shaft, fill=bone)
    for k in range(5):  # barbs on one edge
        bx = L * (0.25 + k * 0.13)
        d.polygon([(bx, cy - H * 0.16), (bx + L * 0.09, cy - H * 0.14), (bx - L * 0.01, cy - H * 0.62)], fill=bone)
    # shading
    arr = np.asarray(img, dtype=np.float32)
    yy = np.linspace(-1, 1, arr.shape[0])[:, None]
    shade = 1.05 - 0.35 * np.clip(yy, -1, 1) ** 2 - 0.15 * (yy > 0)
    arr[..., :3] *= shade[..., None]
    rng = np.random.default_rng(2)
    arr[..., :3] *= 0.92 + 0.08 * rng.random(arr.shape[:2])[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


class Seabed:
    """Underwater scene: trawler above, peat lump and barbed antler point (illustration)."""

    def __init__(self, w, h, p):
        self.w, self.h, self.p = w, h, p
        y = np.linspace(0, 1, h)[:, None, None]
        top, bot = np.array([0.14, 0.42, 0.48]), np.array([0.01, 0.05, 0.08])
        self.bg = np.broadcast_to(lerp(top, bot, y ** 0.8), (h, w, 3)).astype(np.float32).copy()
        floor = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(floor)
        rng = np.random.default_rng(4)
        fy = h * 0.78
        xs = np.arange(0, w + 8, 8)
        ys = fy + 18 * np.sin(xs / w * 7) + 10 * np.sin(xs / w * 19 + 1)
        d.polygon([(0, h)] + list(zip(xs, ys)) + [(w, h)], fill=(30, 36, 30, 255))
        for _ in range(160):
            x, yy = rng.uniform(0, w), rng.uniform(fy + 10, h)
            r = rng.uniform(2, 9)
            d.ellipse((x - r, yy - r * 0.5, x + r, yy + r * 0.5), fill=(44, 50, 40, 255))
        self.floor = floor.filter(ImageFilter.GaussianBlur(1.5))
        self.fy = fy
        self.point = _antler_point(w * 0.62 if h > w else w * 0.34)
        self.particles = rng.random((90, 3))
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.xx, self.yy = xx, yy
        self.xq, self.yq = xx[::4, ::4], yy[::4, ::4]

    def frame(self, t, dur, i):
        w, h = self.w, self.h
        u = t / max(dur, 1e-6)
        sc = w / 1080 if h > w else h / 1080
        f = self.bg.copy()
        # god rays
        rays = np.zeros(self.xq.shape, np.float32)
        for k in range(5):
            ang = 0.35 + 0.05 * k
            off = (k * 0.21 + 0.05 * math.sin(t * 0.4 + k)) * w
            dist = (self.xq - off - self.yq * ang)
            rays += np.exp(-(dist / (40 + 15 * k)) ** 2) * (0.5 + 0.5 * math.sin(t * 0.9 + k * 1.7))
        rays *= np.clip(1 - self.yq / (h * 0.9), 0, 1)
        rays = np.asarray(Image.fromarray(rays.astype(np.float32), mode="F").resize((w, h), Image.BILINEAR))
        f += rays[..., None] * np.array([0.10, 0.22, 0.22], np.float32)
        img = Image.fromarray((np.clip(f, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
        img.alpha_composite(self.floor)
        d = ImageDraw.Draw(img)
        # surface + trawler silhouette, trawl wire to the seabed
        sy = h * 0.06
        bx = w * (0.30 + 0.05 * u)
        d.polygon([(bx - 170 * sc, sy), (bx + 190 * sc, sy), (bx + 150 * sc, sy + 55 * sc), (bx - 140 * sc, sy + 50 * sc)], fill=(4, 10, 14, 255))
        d.line((bx + 120 * sc, sy + 40 * sc, w * 0.55, self.fy - 40 * sc), fill=(10, 20, 24, 220), width=int(3 * sc))
        # net
        nx, ny = w * 0.55, self.fy - 40 * sc
        for k in range(6):
            d.line((nx + k * 22 * sc, ny - k * 6 * sc, nx + 160 * sc, ny + 30 * sc), fill=(12, 24, 28, 160), width=int(2 * sc))
        # peat lump + reveal of the point
        cx, cy = w * 0.5, h * (0.56 if h > w else 0.55)
        reveal = ease((u - 0.30) / 0.30)
        d.ellipse((cx - 210 * sc, cy - 90 * sc + 260 * sc * (1 - reveal), cx + 210 * sc, cy + 90 * sc + 260 * sc * (1 - reveal)),
                  fill=(38, 26, 18, int(255 * (1 - reveal * 0.85))))
        frame = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
        if reveal > 0:
            if not hasattr(self, "_halo"):
                self._halo = np.exp(-(((self.xx - cx) / (w * 0.45)) ** 2 + ((self.yy - cy) / (h * 0.10)) ** 2)).astype(np.float32)
            halo = self._halo
            frame += halo[..., None] * np.array([0.25, 0.22, 0.15], np.float32) * reveal
            ang = -8 + 6 * math.sin(t * 0.6)
            spr = self.point.rotate(ang, resample=Image.BICUBIC, expand=True)
            s = 0.92 + 0.08 * reveal
            spr = spr.resize((int(spr.width * s), int(spr.height * s)), Image.BICUBIC)
            a = np.asarray(spr, dtype=np.float32) / 255.0
            a[..., 3] *= reveal
            x0 = int(cx - spr.width / 2)
            y0 = int(cy - spr.height / 2 + math.sin(t * 1.2) * 8 * sc)
            x1, y1 = x0 + spr.width, y0 + spr.height
            xa, ya = max(0, x0), max(0, y0)
            xb, yb = min(w, x1), min(h, y1)
            sub = a[ya - y0:yb - y0, xa - x0:xb - x0]
            al = sub[..., 3:4]
            frame[ya:yb, xa:xb] = frame[ya:yb, xa:xb] * (1 - al) + sub[..., :3] * al
        # drifting particles
        ov = Overlay(w, h)
        for px, py, ps in self.particles:
            x = (px * w + t * 12 * ps) % w
            y = (py * h - t * 18 * ps) % h
            r = 1.5 + ps * 2.5
            ov.ellipse((x - r * sc, y - r * sc, x + r * sc, y + r * sc), fill=(200, 230, 225), alpha=0.25 + 0.3 * ps)
        al = ease_out((u - 0.55) / 0.12)
        ly = cy - h * (0.20 if h > w else 0.30)
        for k, line in enumerate(self.p.get("caption_lines", [])):
            fs = 32 if k == 0 else 26
            ov.tracked((w / 2, ly + k * 50 * sc), line, font("Montserrat", int(fs * sc), "Bold" if k == 0 else "SemiBold"),
                       tracking=0.18, alpha=al, fill=(245, 200, 69) if k == 0 else (255, 255, 255))
        ov.text((w / 2, h * (0.115 if h > w else 0.05)), "ILLUSTRATION", font("Montserrat", int(20 * sc), "Medium"), alpha=0.7)
        return ov.apply(frame)


class TitleCard:
    """Typographic card over a blurred, darkened background scene."""

    def __init__(self, w, h, p, bg_scene=None):
        self.w, self.h, self.p, self.bg = w, h, p, bg_scene

    def frame(self, t, dur, i):
        w, h = self.w, self.h
        u = t / max(dur, 1e-6)
        sc = w / 1080 if h > w else h / 1080
        if self.bg is not None:
            f = self.bg.frame(t, dur, i)
            pil = Image.fromarray((np.clip(f, 0, 1) * 255).astype(np.uint8))
            pil = pil.resize((w // 4, h // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2.5)).resize((w, h), Image.BILINEAR)
            f = np.asarray(pil, dtype=np.float32) / 255.0 * 0.45
        else:
            f = np.zeros((h, w, 3), np.float32)
        ov = Overlay(w, h)
        al = ease_out(u / 0.18)
        cy = h * 0.40
        ov.tracked((w / 2, cy), self.p["title"], font("Cinzel", int(self.p.get("size", 118) * sc), "Bold"), tracking=0.1,
                   alpha=al, fill=(255, 243, 214))
        if self.p.get("subtitle"):
            ov.line([(w / 2 - 160 * sc * al, cy + 90 * sc), (w / 2 + 160 * sc * al, cy + 90 * sc)], fill=(245, 200, 69), width=int(3 * sc), alpha=al)
            ov.tracked((w / 2, cy + 140 * sc), self.p["subtitle"], font("Montserrat", int(34 * sc), "SemiBold"), tracking=0.28,
                       alpha=ease_out((u - 0.15) / 0.2), fill=(245, 200, 69))
        return ov.apply(f)


class ImageScene:
    """Licensed still image with a slow camera move. Landscape images in a vertical frame are shown
    'contained' over a blurred copy of themselves, so nothing important is cropped away.
    The licence credit is printed small on screen and listed in the description."""

    def __init__(self, w, h, p):
        from ..config import ROOT
        self.w, self.h, self.p = w, h, p
        path = p["path"]
        im = Image.open(path if str(path).startswith("/") or ":" in str(path) else ROOT / path).convert("RGB")
        self.contain = (im.width / im.height) > (w / h) * 1.35
        if self.contain:
            s = w / im.width * 1.0
            self.fg = im.resize((int(im.width * s * 1.12), int(im.height * s * 1.12)), Image.LANCZOS)
            sb = max(w / im.width, h / im.height)
            bg = im.resize((int(im.width * sb), int(im.height * sb)), Image.BILINEAR)
            bx, by = (bg.width - w) // 2, (bg.height - h) // 2
            bg = bg.crop((bx, by, bx + w, by + h)).resize((w // 8, h // 8)).filter(ImageFilter.GaussianBlur(3)).resize((w, h), Image.BILINEAR)
            self.bg = np.asarray(bg, dtype=np.float32) / 255.0 * 0.45
        else:
            s = max(w / im.width, h / im.height) * 1.15
            self.im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        self.k = p.get("move", hash(str(path)) % 4)

    def frame(self, t, dur, i):
        w, h = self.w, self.h
        u = ease(t / max(dur, 1e-6))
        sc = w / 1080 if h > w else h / 1080
        if self.contain:
            frame = self.bg.copy()
            z = lerp(1.0, 1.08, u) if self.k % 2 == 0 else lerp(1.08, 1.0, u)
            fw, fh = self.fg.width, self.fg.height
            cw, ch = fw / 1.12 / z * 1.0, fh / 1.12 / z
            dx = (fw - cw) * (0.5 + (0.3 if self.k in (1, 2) else -0.3) * (u - 0.5))
            dy = (fh - ch) / 2
            out_w = w
            out_h = int(out_w * ch / cw)
            crop = self.fg.resize((out_w, out_h), Image.BILINEAR, box=(dx, dy, dx + cw, dy + ch))
            a = np.asarray(crop, dtype=np.float32) / 255.0
            y0 = (h - out_h) // 2 - int(h * 0.04 if h > w else 0)
            frame[y0:y0 + out_h, :] = a
        else:
            z0, z1 = self.p.get("zoom", [1.0, 1.12] if self.k % 2 == 0 else [1.12, 1.0])
            z = lerp(z0, z1, u)
            W, H = self.im.size
            if W / H > w / h:
                ch = H / z
                cw = ch * w / h
            else:
                cw = W / z
                ch = cw * h / w
            px0, px1 = self.p.get("pan", [0.45, 0.55] if self.k in (0, 3) else [0.55, 0.45])
            cx = W * lerp(px0, px1, u)
            x0 = min(max(cx - cw / 2, 0), W - cw)
            y0 = (H - ch) / 2
            frame = np.asarray(self.im.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)), dtype=np.float32) / 255.0
        ov = Overlay(w, h)
        if self.p.get("label"):
            al = ease_out((t / max(dur, 1e-6) - 0.05) / 0.15)
            ov.tracked((w / 2, h * (0.16 if h > w else 0.10)), self.p["label"].upper()[:34],
                       font("Montserrat", int(34 * sc), "Bold"), tracking=0.18, alpha=al, fill=(245, 200, 69))
        if self.p.get("credit"):
            ov.text((w / 2, h * (0.115 if h > w else 0.04)), self.p["credit"][:90], font("Montserrat", int(19 * sc), "Medium"),
                    alpha=0.75)
        return ov.apply(frame)
