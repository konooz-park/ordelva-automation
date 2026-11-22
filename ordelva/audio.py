"""Original score + sound design generated in code (owned by the channel, no licence issues),
and the final voice/music mix with ducking and loudness normalisation (FFmpeg)."""
import json
import subprocess
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve, butter, sosfilt

SR = 48000
NOTE = {"C": -9, "C#": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5, "F": -4, "F#": -3, "G": -2,
        "G#": -1, "Ab": -1, "A": 0, "A#": 1, "Bb": 1, "B": 2}


def hz(name, octave):
    return 440.0 * 2 ** ((NOTE[name] + 12 * (octave - 4)) / 12)


PROGRESSIONS = {
    "mystery": [("D", ["D", "F", "A"]), ("Bb", ["Bb", "D", "F"]), ("F", ["F", "A", "C"]), ("C", ["C", "E", "G"])],
    "wonder": [("A", ["A", "C#", "E"]), ("F#", ["F#", "A", "C#"]), ("D", ["D", "F#", "A"]), ("E", ["E", "G#", "B"])],
}


def _pad_note(f, n, rng, harmonics=7, detune=(-0.06, 0.0, 0.07)):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in detune:
        ff = f * 2 ** (d / 12)
        ph = rng.uniform(0, 2 * np.pi)
        for k in range(1, harmonics + 1):
            out += np.sin(2 * np.pi * ff * k * t + ph * k) / (k ** 1.6)
    return out / (len(detune) * 2)


def _env(n, a, r):
    e = np.ones(n)
    na, nr = min(int(a * SR), n // 2), min(int(r * SR), n // 2)
    e[:na] = np.linspace(0, 1, na) ** 2
    e[n - nr:] *= np.linspace(1, 0, nr) ** 2
    return e


def _lp(x, cutoff):
    sos = butter(2, cutoff, "low", fs=SR, output="sos")
    return sosfilt(sos, x)


def _bp(x, lo, hi):
    sos = butter(2, [lo, hi], "band", fs=SR, output="sos")
    return sosfilt(sos, x)


def _reverb(stereo, rng, seconds=2.8, wet=0.35):
    n = int(seconds * SR)
    decay = np.exp(-np.linspace(0, 7, n))
    ir = np.stack([rng.standard_normal(n) * decay, rng.standard_normal(n) * decay], 1)
    ir[:, 0] = _lp(ir[:, 0], 6000)
    ir[:, 1] = _lp(ir[:, 1], 6000)
    ir /= np.sqrt((ir ** 2).sum(0))
    out = np.stack([fftconvolve(stereo[:, c], ir[:, c])[: len(stereo)] for c in range(2)], 1)
    return stereo * (1 - wet) + out * wet * 1.6


def compose(duration, cues, path, mood="mystery", seed=7, chord_len=6.0):
    """cues: list of {"t": seconds, "kind": "whoosh"|"impact"|"tension_on"|"tension_off"|"swell"|"end"}"""
    rng = np.random.default_rng(seed)
    n = int((duration + 1.5) * SR)
    L = np.zeros(n)
    R = np.zeros(n)
    prog = PROGRESSIONS.get(mood, PROGRESSIONS["mystery"])
    # --- pads
    t0, ci = 0.0, 0
    while t0 < duration + 1.5:
        root, chord = prog[ci % len(prog)]
        seg = int((chord_len + 2.0) * SR)
        s0 = int(t0 * SR)
        seg = min(seg, n - s0)
        if seg <= SR // 2:
            break
        env = _env(seg, 1.6, 2.2)
        bass = np.sin(2 * np.pi * hz(root, 2) * np.arange(seg) / SR) * 0.45
        notes = [hz(c, 3) for c in chord] + [hz(chord[0], 4)]
        padL = sum(_pad_note(f, seg, rng) for f in notes)
        padR = sum(_pad_note(f * 1.002, seg, rng) for f in notes)
        L[s0:s0 + seg] += (padL * 0.22 + bass) * env
        R[s0:s0 + seg] += (padR * 0.22 + bass) * env
        t0 += chord_len
        ci += 1
    L, R = _lp(L, 2200), _lp(R, 2200)
    # --- airy texture (filtered noise, slow swell)
    noise = rng.standard_normal((n, 2))
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * np.arange(n) / SR / 9.0)
    for c, arr in enumerate((L, R)):
        arr += _bp(noise[:, c], 300, 1800) * 0.025 * lfo
    # --- cues
    tension = []
    on = None
    for c in sorted(cues, key=lambda x: x["t"]):
        if c["kind"] == "tension_on":
            on = c["t"]
        elif c["kind"] == "tension_off" and on is not None:
            tension.append((on, c["t"]))
            on = None
    if on is not None:
        tension.append((on, duration))
    for a, b in tension:     # low heartbeat-like drum pulse
        t = a
        while t < b:
            s0 = int(t * SR)
            m = int(0.7 * SR)
            if s0 + m >= n:
                break
            tt = np.arange(m) / SR
            f = 58 * np.exp(-tt * 3) + 38
            hit = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 6) * 0.55
            L[s0:s0 + m] += hit
            R[s0:s0 + m] += hit
            t += 0.85
    for c in cues:
        s0 = int(c["t"] * SR)
        if c["kind"] == "whoosh":
            m = int(1.1 * SR)
            if s0 - m // 2 < 0 or s0 + m // 2 >= n:
                continue
            tt = np.linspace(0, 1, m)
            env = np.sin(np.pi * tt) ** 3
            w = _bp(rng.standard_normal(m), 400, 5000) * env * 0.12
            L[s0 - m // 2:s0 + m // 2] += w[: m // 2 * 2]
            R[s0 - m // 2:s0 + m // 2] += w[::-1][: m // 2 * 2]
        elif c["kind"] == "impact":
            m = int(4.0 * SR)
            if s0 + m >= n:
                m = n - s0 - 1
            tt = np.arange(m) / SR
            f = 90 * np.exp(-tt * 1.5) + 28
            boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 1.1) * 0.9
            rumble = _lp(rng.standard_normal(m), 250) * np.exp(-tt * 0.8) * 0.5
            L[s0:s0 + m] += boom + rumble
            R[s0:s0 + m] += boom + rumble
        elif c["kind"] == "swell":
            m = int(3.0 * SR)
            if s0 - m < 0:
                continue
            env = np.linspace(0, 1, m) ** 3
            sw = _bp(rng.standard_normal(m), 200, 3000) * env * 0.12
            L[s0 - m:s0] += sw
            R[s0 - m:s0] += sw
    st = np.stack([L, R], 1)
    st = _reverb(st, rng)
    # fade out at end
    fo = int(2.0 * SR)
    end = int(duration * SR)
    st = st[: end]
    st[-fo:] *= np.linspace(1, 0, fo)[:, None]
    st[: int(0.3 * SR)] *= np.linspace(0, 1, int(0.3 * SR))[:, None]
    st /= np.max(np.abs(st)) + 1e-9
    sf.write(path, (st * 0.89).astype(np.float32), SR, subtype="PCM_16")
    return path


def _loudness(path, filt):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", filt + ":print_format=json", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    j = err[err.rfind("{"): err.rfind("}") + 1]
    return json.loads(j)


def mix(voice_wav, music_wav, out_wav, target_lufs=-14.0, music_db=-21.0):
    """Duck music under narration, sum, then 2-pass loudnorm to the YouTube target."""
    pre = out_wav + ".pre.wav"
    fc = (f"[0:a]aresample={SR},aformat=channel_layouts=stereo,highpass=f=70,"
          f"acompressor=threshold=-20dB:ratio=3:attack=5:release=120,asplit=2[v][vsc];"
          f"[1:a]aresample={SR},volume={music_db}dB[m];"
          f"[m][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=40:release=500[md];"
          f"[v][md]amix=inputs=2:normalize=0:duration=longest[out]")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice_wav, "-i", music_wav,
                    "-filter_complex", fc, "-map", "[out]", pre], check=True)
    m = _loudness(pre, f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11")
    filt = (f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", pre, "-af", filt,
                    "-ar", str(SR), out_wav], check=True)
    return out_wav
