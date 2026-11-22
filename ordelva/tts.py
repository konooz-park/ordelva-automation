"""English narration with Kokoro-82M (Apache-2.0) running locally through ONNX Runtime.

Every sentence is synthesised separately, so we know its exact start/end time.
Word times inside a sentence are estimated from syllable weights; if faster-whisper
is installed with a model, `align.refine_with_whisper` replaces them with ASR timings.
"""
import re
import numpy as np
import soundfile as sf
from .config import MODELS

SR = 24000
_kokoro = None


def _engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
    return _kokoro


def split_sentences(text: str):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p]


def _syllables(word: str) -> float:
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    if not w:
        return 0.5
    if w.isdigit():
        return 1.2 * len(w)
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


def word_times(caption_words, start, end):
    """Spread caption words over [start, end] using syllable + punctuation weights."""
    weights = []
    for w in caption_words:
        wt = _syllables(w) + 0.15
        if re.search(r"[,;:]$", w):
            wt += 0.9
        elif re.search(r"[.!?]$", w):
            wt += 1.2
        weights.append(wt)
    total = sum(weights) or 1
    t, out = start, []
    for w, wt in zip(caption_words, weights):
        d = (end - start) * wt / total
        out.append((w, t, t + d))
        t += d
    return out


def _trim(audio, thr=0.01):
    idx = np.where(np.abs(audio) > thr)[0]
    if len(idx) == 0:
        return audio
    a, b = max(0, idx[0] - int(0.03 * SR)), min(len(audio), idx[-1] + int(0.06 * SR))
    return audio[a:b]


def narrate_beats(beats, out_wav, voice="bm_george", lang="en-gb", speed=1.0,
                  lead_in=0.35, sentence_gap=0.18, default_pause=0.35, tail=0.0):
    """Synthesise all beats. Returns timeline: list of dicts with start/end and word timings."""
    k = _engine()
    pieces, timeline, t = [np.zeros(int(lead_in * SR), np.float32)], [], lead_in
    for i, beat in enumerate(beats):
        say = beat.get("say", beat["text"])
        cap = beat.get("text", say)
        s_say, s_cap = split_sentences(say), split_sentences(cap)
        if len(s_say) != len(s_cap):          # captions must mirror spoken sentences
            s_say, s_cap = [say], [cap]
        beat_start, words = t, []
        for j, (ss, sc) in enumerate(zip(s_say, s_cap)):
            audio, sr = k.create(ss, voice=voice, speed=beat.get("speed", speed), lang=lang)
            assert sr == SR
            audio = _trim(audio.astype(np.float32))
            st, en = t, t + len(audio) / SR
            words += word_times(sc.split(), st, en)
            pieces.append(audio)
            t = en
            if j < len(s_say) - 1:
                pieces.append(np.zeros(int(sentence_gap * SR), np.float32))
                t += sentence_gap
        speech_end = t
        pause = beat.get("pause", default_pause)
        pieces.append(np.zeros(int(pause * SR), np.float32))
        t += pause
        timeline.append({"i": i, "start": beat_start, "speech_end": speech_end, "end": t, "words": words})
    pieces.append(np.zeros(int(tail * SR), np.float32))
    t += tail
    timeline[-1]["end"] = t
    audio = np.concatenate(pieces)
    sf.write(out_wav, audio, SR, subtype="PCM_16")
    return timeline, len(audio) / SR
