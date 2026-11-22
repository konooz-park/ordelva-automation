"""Burned-in, word-highlighted captions (ASS format, rendered by FFmpeg/libass)."""
import re


def _ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def group_words(words, max_words=3, max_chars=18):
    groups, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or re.search(r"[.,!?;:]$", w[0]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _clean(w):
    return w.replace("{", "").replace("}", "")


def build_ass(timeline, path, w, h, fmt="short", font="Anton", highlight="&H0045C8F5&"):
    # ASS colours are &HAABBGGRR. highlight = warm gold (F5C845)
    size = 92 if fmt == "short" else 64
    margin_v = int(h * 0.30) if fmt == "short" else int(h * 0.08)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,6,3,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    all_groups = []
    for beat in timeline:
        all_groups += group_words(beat["words"])
    for gi, g in enumerate(all_groups):
        g_start, g_end = g[0][1], g[-1][2]
        if gi + 1 < len(all_groups):
            nxt = all_groups[gi + 1][0][1]
            if nxt - g_end < 0.35:
                g_end = nxt
        words_up = [_clean(x[0]).upper() for x in g]
        for wi, (wd, ws, we) in enumerate(g):
            st = g_start if wi == 0 else ws
            en = g_end if wi == len(g) - 1 else g[wi + 1][1]
            parts = []
            for k, txt in enumerate(words_up):
                parts.append("{\\c" + highlight + "}" + txt + "{\\c&H00FFFFFF&}" if k == wi else txt)
            pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(st)},{_ts(en)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines) + "\n")
    return len(all_groups)


def build_srt(timeline, path):
    """Plain sentence-level SRT, uploaded to YouTube as a closed-caption track."""
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    n, out = 1, []
    for beat in timeline:
        words = beat["words"]
        chunk = []
        for w in words:
            chunk.append(w)
            if re.search(r"[.!?]$", w[0]) or len(chunk) >= 10:
                out.append(f"{n}\n{ts(chunk[0][1])} --> {ts(chunk[-1][2])}\n{' '.join(x[0] for x in chunk)}\n")
                n, chunk = n + 1, []
        if chunk:
            out.append(f"{n}\n{ts(chunk[0][1])} --> {ts(chunk[-1][2])}\n{' '.join(x[0] for x in chunk)}\n")
            n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
