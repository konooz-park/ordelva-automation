"""Download runtime assets with pinned SHA-256 checksums (used by GitHub Actions and setup)."""
import hashlib
import sys
import requests
from .config import ROOT

FILES = {
    "models/kokoro-v1.0.onnx": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
                                "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
    "models/voices-v1.0.bin": ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
                               "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
    "assets/fonts/Anton-Regular.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
                                       "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab"),
    "assets/fonts/Cinzel-VF.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
                                   "f4d83d34d1f6c741193e4acf4b3dff9531e5a67b6aa65228d00a7db72a4e0f34"),
    "assets/fonts/Montserrat-VF.ttf": ("https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
                                       "0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7"),
    "assets/data/etopo20data.gz": ("https://raw.githubusercontent.com/matplotlib/basemap/master/doc/examples/etopo20data.gz",
                                   "bd6549bb0a675d2978d1dee1609fc4cec7e4d74b98d4fe49c0e8a2e8c8f3b8ce"),
    "assets/data/etopo20lats.gz": ("https://raw.githubusercontent.com/matplotlib/basemap/master/doc/examples/etopo20lats.gz",
                                   "3201109f72a8371d1fee6396292618c9b05cae0a55abf8b2117bb2ef1f7e97ce"),
    "assets/data/etopo20lons.gz": ("https://raw.githubusercontent.com/matplotlib/basemap/master/doc/examples/etopo20lons.gz",
                                   "95109988351bed186a886c6dd2a607455939013dfc49f7b7c61997d3389802b7"),
}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    bad = []
    for rel, (url, digest) in FILES.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and sha(p) == digest:
            continue
        print("downloading", rel)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        p.write_bytes(r.content)
        if sha(p) != digest:
            p.unlink()
            bad.append(rel)
    if bad:
        print("CHECKSUM MISMATCH:", bad)
        sys.exit(1)
    print("assets ok")


if __name__ == "__main__":
    main()
