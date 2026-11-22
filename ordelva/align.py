"""Optional Whisper pass (faster-whisper, MIT).

1. Transcribes the finished narration and compares it with the script (QA: catches
   mispronounced / skipped words).
2. If the transcript matches well, replaces estimated word times with ASR word times.

Needs the model to be downloadable from huggingface.co on first use (≈150 MB for base.en).
If it is unavailable, the pipeline keeps the TTS-derived timings and logs that it skipped.
"""
import difflib
import re


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower())


def transcribe(wav, model_size=None):
    from faster_whisper import WhisperModel
    from .config import load_config
    cfg = load_config()
    dev = cfg.get("whisper_device", "cpu")          # "cuda" only if NVIDIA + CUDA 12/cuDNN 9 are installed
    m = WhisperModel(model_size or cfg.get("whisper_model", "base.en"), device=dev,
                     compute_type="float16" if dev == "cuda" else "int8")
    # decode ourselves (soundfile + scipy) instead of PyAV: newer PyAV releases broke faster-whisper's decoder
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    audio, sr = sf.read(wav, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != 16000:
        g = gcd(sr, 16000)
        audio = resample_poly(audio, 16000 // g, sr // g).astype(np.float32)
    segs, _ = m.transcribe(audio, word_timestamps=True, vad_filter=False, language="en")
    words = []
    for s in segs:
        for w in s.words:
            words.append((w.word.strip(), w.start, w.end))
    return words


def script_match_ratio(script_text, asr_words):
    a = _norm(script_text).split()
    b = _norm(" ".join(w[0] for w in asr_words)).split()
    return difflib.SequenceMatcher(None, a, b).ratio()


def refine_with_whisper(timeline, wav, log=None, spoken_text=None):
    """Replace estimated caption word times with Whisper word times where words match;
    words that differ (e.g. "1931" vs "nineteen thirty-one") are interpolated between matched neighbours."""
    try:
        asr = transcribe(wav)
    except Exception as e:  # model not downloadable / not installed
        if log:
            log.warning("Whisper refinement skipped: %s", e)
        return timeline, None
    flat = [(bi, wi, w) for bi, b in enumerate(timeline) for wi, w in enumerate(b["words"])]
    script = spoken_text or " ".join(x[2][0] for x in flat)
    ratio = script_match_ratio(script, asr)
    if ratio < 0.80:
        return timeline, ratio
    a = [_norm(x[2][0]) for x in flat]
    b = [_norm(x[0]) for x in asr]
    new = [None] * len(flat)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                new[i1 + k] = (asr[j1 + k][1], asr[j1 + k][2])
        elif tag == "replace" and j2 > j1:
            # spread the ASR span over the differing caption words
            s0, e0 = asr[j1][1], asr[j2 - 1][2]
            n = i2 - i1
            for k in range(n):
                new[i1 + k] = (s0 + (e0 - s0) * k / n, s0 + (e0 - s0) * (k + 1) / n)
    for idx, (bi, wi, w) in enumerate(flat):
        if new[idx]:
            timeline[bi]["words"][wi] = (w[0], new[idx][0], new[idx][1])
    return timeline, ratio
