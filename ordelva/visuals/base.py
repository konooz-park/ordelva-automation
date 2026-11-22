"""Shared drawing helpers: fonts, easing, overlays, grading."""
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from ..config import FONTS


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def lerp(a, b, x):
    return a + (b - a) * x


@lru_cache(maxsize=64)
def font(name="Montserrat", size=48, weight="Bold"):
    files = {"Montserrat": "Montserrat-VF.ttf", "Cinzel": "Cinzel-VF.ttf", "Anton": "Anton-Regular.ttf"}
    f = ImageFont.truetype(str(FONTS / files[name]), size)
    if name in ("Montserrat", "Cinzel"):
        try:
            f.set_variation_by_name(weight)
            wmap = {"Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400, "Medium": 500, "SemiBold": 600,
                    "Bold": 700, "ExtraBold": 800, "Black": 900}
            f._ordelva_w = wmap.get(weight, 700)
        except Exception:
            pass
    return f


_small = {}


def _small_font(f):
    k = (f.path, f.size, getattr(f, "_ordelva_w", None))
    if k not in _small:
        sf = ImageFont.truetype(f.path, max(4, f.size // 4))
        try:
            axes = f.get_variation_axes()
            if axes:
                sf.set_variation_by_axes([f._ordelva_w] if hasattr(f, "_ordelva_w") else [ax["default"] for ax in axes])
        except Exception:
            pass
        _small[k] = sf
    return _small[k]


class Overlay:
    """RGBA text/graphics layer composited onto an RGB float frame."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)
        # one shared shadow layer at 1/4 resolution, blurred once in apply()
        self.sh = Image.new("L", (w // 4, h // 4), 0)
        self.sd = ImageDraw.Draw(self.sh)
        self.used = False
        self.shadow_used = False

    def text(self, xy, s, f, fill=(255, 255, 255), alpha=1.0, anchor="mm", shadow=True, spacing=0,
             stroke=0, stroke_fill=(0, 0, 0)):
        if alpha <= 0.01:
            return
        self.used = True
        a = int(255 * alpha)
        if shadow:
            self.shadow_used = True
            sf = _small_font(f)
            self.sd.text(((xy[0] + 3) / 4, (xy[1] + 5) / 4), s, font=sf, fill=int(a * 0.8), anchor=anchor,
                         spacing=spacing / 4, align="center")
        self.d.text(xy, s, font=f, fill=fill + (a,), anchor=anchor, spacing=spacing, align="center",
                    stroke_width=stroke, stroke_fill=stroke_fill + (a,))

    def tracked(self, xy, s, f, tracking=0.15, **kw):
        """Letter-spaced text (cinematic titles)."""
        widths = [self.d.textlength(ch, font=f) for ch in s]
        extra = f.size * tracking
        total = sum(widths) + extra * (len(s) - 1)
        x = xy[0] - total / 2
        for ch, wd in zip(s, widths):
            self.text((x + wd / 2, xy[1]), ch, f, **kw)
            x += wd + extra

    def line(self, pts, fill=(255, 255, 255), width=3, alpha=1.0):
        self.used = True
        self.d.line(pts, fill=fill + (int(255 * alpha),), width=width)

    def ellipse(self, box, outline=None, fill=None, width=3, alpha=1.0):
        self.used = True
        a = int(255 * alpha)
        self.d.ellipse(box, outline=(outline + (a,)) if outline else None, fill=(fill + (a,)) if fill else None,
                       width=width)

    def apply(self, frame):
        if not self.used:
            return frame
        if self.shadow_used:
            sh = self.sh.filter(ImageFilter.GaussianBlur(2.0)).resize((self.w, self.h), Image.BILINEAR)
            sa = np.asarray(sh, dtype=np.float32)[..., None] / 255.0 * 0.85
            frame = frame * (1 - sa)
        o = np.asarray(self.img, dtype=np.float32) / 255.0
        a = o[..., 3:4]
        return frame * (1 - a) + o[..., :3] * a


_vig_cache = {}


def vignette(w, h, strength=0.55):
    k = (w, h, strength)
    if k not in _vig_cache:
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        r = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / 1.414
        _vig_cache[k] = (1 - strength * np.clip(r, 0, 1) ** 2.2)[..., None]
    return _vig_cache[k]


_grain = {}


def grain(w, h, i, amount=0.025):
    key = (w, h)
    if key not in _grain:
        rng = np.random.default_rng(3)
        _grain[key] = [rng.standard_normal((h // 2, w // 2)).astype(np.float32) for _ in range(6)]
    g = _grain[key][(i // 2) % 6]
    g = np.repeat(np.repeat(g, 2, 0), 2, 1)[:h, :w]
    return g[..., None] * amount


def finish(frame, i, vig=0.5, grain_amt=0.02):
    """Final grade: vignette + film grain + clip. frame is float 0..1."""
    w, h = frame.shape[1], frame.shape[0]
    f = frame * vignette(w, h, vig) + grain(w, h, i, grain_amt)
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def zoom_crop(arr_img: Image.Image, zoom, cx, cy, w, h):
    """Crop a window (zoom>=1) centred at (cx,cy) in pixels and resize back to w x h."""
    cw, ch = w / zoom, h / zoom
    x0 = min(max(cx - cw / 2, 0), w - cw)
    y0 = min(max(cy - ch / 2, 0), h - ch)
    return arr_img.resize((w, h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)), (x0, y0, zoom)
