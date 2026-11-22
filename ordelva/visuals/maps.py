"""Animated sea-level maps built from real elevation data.

Data: ETOPO 20-arc-minute global relief (NOAA, public domain; copy shipped with matplotlib/basemap examples)
+ present-day coastline from `global-land-mask` (GLOBE 1 km, public domain).
The 'past coastline' is a simplified reconstruction: modern seabed depth vs. a lowered sea level
(it ignores isostatic rebound and sediment changes). The video says so on screen.
"""
from functools import lru_cache
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates, gaussian_filter, zoom as nd_zoom
from ..config import ASSETS
from .base import Overlay, font, ease, ease_out, lerp


@lru_cache(maxsize=1)
def _etopo():
    d = np.loadtxt(ASSETS / "data" / "etopo20data.gz")
    la = np.loadtxt(ASSETS / "data" / "etopo20lats.gz")
    lo = np.loadtxt(ASSETS / "data" / "etopo20lons.gz")
    return d, la, lo


REGIONS = {
    # centre lat/lon, longitude span (degrees). Latitude span follows the frame aspect.
    "north_sea": {"lat": 56.5, "lon": 2.5, "lon_span": 20.0},
}


class World:
    def __init__(self, w, h, region="north_sea"):
        # NB: works for any region dict {"lat","lon","lon_span"}; longitudes may cross ±180
        from global_land_mask import globe
        r = REGIONS[region] if isinstance(region, str) else region
        self.w, self.h = w, h
        k = np.cos(np.radians(r["lat"]))
        lon_span = r["lon_span"]
        lat_span = lon_span * k * h / w
        self.lon0, self.lon1 = r["lon"] - lon_span / 2, r["lon"] + lon_span / 2
        self.lat1, self.lat0 = r["lat"] + lat_span / 2, r["lat"] - lat_span / 2
        lat = np.linspace(self.lat1, self.lat0, h)
        lon = np.linspace(self.lon0, self.lon1, w)
        LON, LAT = np.meshgrid(lon, lat)
        d, la, lo = _etopo()
        LON = np.where(LON > 180, LON - 360, np.where(LON < -180, LON + 360, LON))
        lo2 = np.where(LON < lo[0], LON + 360, LON)
        fi = (LAT - la[0]) / (la[1] - la[0])
        fj = (lo2 - lo[0]) / (lo[1] - lo[0])
        E = map_coordinates(d, [fi, fj], order=3).astype(np.float32)
        self.land_now = globe.is_land(LAT, LON)
        # keep modern land above 0 and modern sea below 0 so coasts at sea level 0 are crisp
        E = np.where(self.land_now, np.maximum(E, 2.0), np.minimum(E, -1.0)).astype(np.float32)
        # the 20' grid is too coarse for narrow straits (e.g. Dover): deepen sea pixels with distance from
        # the modern coast (≈1.3 m per km, fading out beyond 15 km), so only near-shore water changes.
        from scipy.ndimage import distance_transform_edt
        km_per_px = (self.lon1 - self.lon0) * 111.0 * k / w
        dist_km = distance_transform_edt(~self.land_now) * km_per_px
        cap = -1.0 - 1.3 * np.where(dist_km < 15, dist_km, 15 * np.exp(-(dist_km - 15) / 10))
        E = np.where(self.land_now, E, np.minimum(E, cap)).astype(np.float32)
        self.E = E
        # hillshade from smoothed elevation
        Es = gaussian_filter(E, 3)
        gy, gx = np.gradient(Es)
        sh = (-gx * 0.7 + gy * 0.7) / 70.0
        self.shade = np.clip(0.9 + sh, 0.75, 1.08).astype(np.float32)[..., None]
        # base land colours
        hi = np.clip(E / 900.0, 0, 1)[..., None]
        modern = lerp(np.array([0.42, 0.40, 0.30]), np.array([0.62, 0.58, 0.50]), hi)
        paleo = np.array([0.36, 0.44, 0.27])  # exposed seabed = 'Doggerland' green-olive
        self.land_rgb = np.where(self.land_now[..., None], modern, paleo).astype(np.float32) * self.shade
        self.paleo = (~self.land_now)

    def xy(self, lat, lon):
        x = (lon - self.lon0) / (self.lon1 - self.lon0) * self.w
        y = (self.lat1 - lat) / (self.lat1 - self.lat0) * self.h
        return x, y

    def render(self, sea_level, glow=0.0, rings=None):
        E = self.E
        mask = E > sea_level
        depth = np.clip((sea_level - E) / 180.0, 0, 1)[..., None]
        sea = lerp(np.array([0.10, 0.36, 0.42], np.float32), np.array([0.02, 0.07, 0.14], np.float32), depth ** 0.6)
        img = np.where(mask[..., None], self.land_rgb, sea)
        if glow > 0:
            pm = (mask & self.paleo)[..., None]
            img = np.where(pm, img * (1 + 0.35 * glow) + np.array([0.05, 0.06, 0.0]) * glow, img)
        # coastline glow (computed at 1/3 resolution for speed)
        small = mask[::3, ::3].astype(np.float32)
        edge = np.abs(np.diff(small, axis=0, prepend=small[:1])) + np.abs(np.diff(small, axis=1, prepend=small[:, :1]))
        edge = gaussian_filter(np.clip(edge, 0, 1), 1.2)
        edge = nd_zoom(edge, 3, order=1)[: self.h, : self.w]
        if edge.shape != (self.h, self.w):
            edge = np.pad(edge, ((0, self.h - edge.shape[0]), (0, self.w - edge.shape[1])))
        img = img + edge[..., None] * np.array([0.55, 0.85, 0.95], np.float32) * 0.9
        if rings is not None:
            img = img + (rings * (~mask))[..., None] * np.array([0.75, 0.95, 1.0], np.float32)
        return img


_worlds = {}


def world(w, h, region="north_sea"):
    k = (w, h, str(region))
    if k not in _worlds:
        _worlds[k] = World(w, h, region)
    return _worlds[k]


class MapScene:
    def __init__(self, w, h, p):
        self.w, self.h, self.p = w, h, p
        self.W = world(w, h, p.get("region", "north_sea"))
        if "tsunami" in p:
            x, y = self.W.xy(p["tsunami"]["lat"], p["tsunami"]["lon"])
            yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
            self.dist = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
            self.src = (x, y)

    def frame(self, t, dur, i):
        p, W = self.p, self.W
        u = t / max(dur, 1e-6)
        a, b = p.get("sea_from", 0), p.get("sea_to", p.get("sea_from", 0))
        su0, su1 = p.get("sea_window", [0.08, 0.92])
        sl = lerp(a, b, ease((u - su0) / (su1 - su0)))
        glow = 0.0
        if p.get("glow_doggerland"):
            glow = 0.5 + 0.5 * np.sin(t * 2.2)
        rings = None
        if "tsunami" in p:
            ts = p["tsunami"].get("start", 0.15) * dur
            rings = np.zeros((self.h, self.w), np.float32)
            for k in range(4):
                tt = t - ts - k * 0.45
                if tt <= 0:
                    continue
                r = tt * self.w * 0.33
                fade = np.exp(-tt * 0.45)
                rings += np.exp(-((self.dist - r) / (10 + 4 * k)) ** 2) * fade * (1.0 - 0.18 * k)
        img = W.render(sl, glow, rings)
        # camera
        z0, z1 = p.get("zoom", [1.0, 1.0])
        z = lerp(z0, z1, ease(u))
        f0 = p.get("focus", [[56.0, 2.5], [56.0, 2.5]])
        if isinstance(f0[0], (int, float)):
            f0 = [f0, f0]
        lat = lerp(f0[0][0], f0[1][0], ease(u))
        lon = lerp(f0[0][1], f0[1][1], ease(u))
        cx, cy = W.xy(lat, lon)
        pil = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
        cw, ch = self.w / z, self.h / z
        x0 = min(max(cx - cw / 2, 0), self.w - cw)
        y0 = min(max(cy - ch / 2, 0), self.h - ch)
        pil = pil.resize((self.w, self.h), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))
        frame = np.asarray(pil, dtype=np.float32) / 255.0

        def tr(la, lo):
            x, y = W.xy(la, lo)
            return (x - x0) * z, (y - y0) * z

        ov = Overlay(self.w, self.h)
        sc = min(self.w, self.h) / 1080
        short = self.h > self.w
        for lb in p.get("labels", []):
            al = ease_out((u - lb.get("at", 0.1)) / 0.12) * (1 - ease((u - lb.get("until", 2)) / 0.1))
            if al <= 0:
                continue
            x, y = tr(lb["lat"], lb["lon"])
            if lb.get("dot", True):
                ov.ellipse((x - 7 * sc, y - 7 * sc, x + 7 * sc, y + 7 * sc), fill=(245, 200, 69), alpha=al)
                dy = -34 * sc
            else:
                dy = 0
            ov.tracked((x, y + dy), lb["text"], font("Montserrat", int(lb.get("size", 34) * sc), "Bold"),
                       tracking=0.18, alpha=al, fill=tuple(lb.get("color", (255, 255, 255))))
        if "tsunami" in p:
            x, y = tr(p["tsunami"]["lat"], p["tsunami"]["lon"])
            al = ease_out((u - p["tsunami"].get("start", 0.15)) / 0.1)
            ov.ellipse((x - 10 * sc, y - 10 * sc, x + 10 * sc, y + 10 * sc), fill=(255, 90, 60), alpha=al)
        if p.get("gauge"):
            self._gauge(ov, sl, u, sc, short)
        if p.get("title"):
            al = ease_out(u / 0.12) * (1 - ease((u - p.get("title_until", 2)) / 0.08))
            ty = 330 * sc if short else 170 * sc
            ov.tracked((self.w / 2, ty), p["title"], font("Cinzel", int(p.get("title_size", 92) * sc), "Bold"),
                       tracking=0.08, alpha=al, fill=(255, 243, 214))
            if p.get("subtitle"):
                ov.tracked((self.w / 2, ty + 95 * sc), p["subtitle"], font("Montserrat", int(34 * sc), "SemiBold"),
                           tracking=0.25, alpha=al * 0.95, fill=(245, 200, 69))
        if p.get("note", True):
            note = p.get("note_text", "Simplified reconstruction from modern seabed depth (NOAA ETOPO)")
            ov.text((self.w / 2, 215 * sc if short else 38 * sc), note,
                    font("Montserrat", int(22 * sc), "Medium"), alpha=0.75, fill=(220, 230, 235))
        frame = ov.apply(frame)
        return frame

    def _gauge(self, ov, sl, u, sc, short):
        al = ease_out(u / 0.1)
        x = 95 * sc
        top, bot = (560 * sc, 1120 * sc) if short else (300 * sc, 760 * sc)
        ov.line([(x, top), (x, bot)], fill=(255, 255, 255), width=int(4 * sc), alpha=0.55 * al)
        for lv in (0, -40, -80, -120):
            yy = top + (bot - top) * (-lv / 120)
            ov.line([(x - 12 * sc, yy), (x + 12 * sc, yy)], fill=(255, 255, 255), width=int(3 * sc), alpha=0.55 * al)
            ov.text((x + 22 * sc, yy), f"{lv} m" if lv else "0 m", font("Montserrat", int(22 * sc), "Medium"),
                    alpha=0.75 * al, anchor="lm", shadow=False)
        yy = top + (bot - top) * (-sl / 120)
        ov.ellipse((x - 13 * sc, yy - 13 * sc, x + 13 * sc, yy + 13 * sc), fill=(245, 200, 69), alpha=al)
        ov.text((x - 20 * sc, top - 45 * sc), "SEA LEVEL", font("Montserrat", int(24 * sc), "Bold"), alpha=al,
                anchor="lm", fill=(245, 200, 69))
        ov.text((x - 20 * sc, bot + 45 * sc), f"{sl:+.0f} m".replace("+0", "0"),
                font("Montserrat", int(40 * sc), "Bold"), alpha=al, anchor="lm")


class MapPin(MapScene):
    """Locator map for any place on Earth: slow push-in to a pulsing pin with the place name."""

    def __init__(self, w, h, p):
        lat, lon = p["lat"], p["lon"]
        q = dict(p)
        q["region"] = {"lat": max(-70, min(70, lat)), "lon": lon, "lon_span": p.get("span", 26.0)}
        q.setdefault("sea_from", 0)
        q.setdefault("zoom", [1.0, 1.6])
        q.setdefault("focus", [[lat, lon], [lat, lon]])
        q["labels"] = [{"text": p.get("name", "").upper()[:28], "lat": lat, "lon": lon, "at": 0.25, "size": 40,
                        "color": [245, 200, 69]}] + q.get("labels", [])
        q.setdefault("note_text", "Map: NOAA ETOPO relief, GLOBE coastline")
        super().__init__(w, h, q)
        self.pin = (lat, lon)

    def frame(self, t, dur, i):
        f = super().frame(t, dur, i)
        return f
