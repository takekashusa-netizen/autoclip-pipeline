"""Brand-safe versions: bleep/mute profanity and flag likely music before posting.

Profanity uses word timings (studio.common.load_words) and the same term list
as lib/content_filter.py, so titles and audio are filtered identically.
Music check is a heuristic, not Content ID: it flags stretches where the
audio is tonal (low spectral flatness) AND has a steady beat for 8+ seconds.
Game soundtracks can trip it too — the output is "review these spans",
with an option to mute them. It cannot promise zero copyright claims.
"""
import os
import re
import sys

from .common import AUDIO_ENC, ROOT, StudioError, ffmpeg, load_words, probe, read_audio_mono

sys.path.insert(0, os.path.join(ROOT, "lib"))
try:
    from content_filter import _FILTERED_TERMS as TERMS  # noqa: E402
except Exception:  # pragma: no cover
    TERMS = ["fuck", "fucking", "fucked", "shit", "bitch", "asshole", "cunt", "dick", "bastard"]

_RX = re.compile(r"^(" + "|".join(re.escape(t) for t in TERMS) + r")(s|es|in|in')?$", re.I)
PAD = 0.06


def profanity_spans(words):
    spans = []
    for w in words:
        tok = re.sub(r"[^\w']", "", w["word"].lower())
        if tok and _RX.match(tok):
            spans.append((max(0.0, w["start"] - PAD), w["end"] + PAD, tok))
    return spans


def music_spans(path, min_len=8.0):
    import numpy as np
    sr = 16000
    a = read_audio_mono(path, sr)
    if len(a) < sr * min_len:
        return []
    n, hop = 1024, 512
    frames = np.lib.stride_tricks.sliding_window_view(a, n)[::hop] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1)) + 1e-9
    flat = np.exp(np.log(spec).mean(axis=1)) / spec.mean(axis=1)          # 1 = noise, ~0 = pure tones
    energy = spec.sum(axis=1)
    onset = np.maximum(0, np.diff(np.log(energy), prepend=np.log(energy[0])))
    fps = sr / hop
    win = int(4 * fps)
    tonal, beat = [], []
    for i in range(0, len(flat) - win, int(fps)):            # 1 s steps, 4 s analysis windows
        tonal.append(np.median(flat[i:i + win]) < 0.12 and energy[i:i + win].mean() > energy.mean() * 0.25)
        o = onset[i:i + win] - onset[i:i + win].mean()
        ac = np.correlate(o, o, "full")[len(o) - 1:]
        lo, hi = int(fps * 60 / 180), int(fps * 60 / 60)        # 60-180 BPM
        strength = ac[lo:hi].max() / (ac[0] + 1e-9) if hi < len(ac) else 0
        beat.append(strength > 0.35)
    flags = [t and b for t, b in zip(tonal, beat)]
    spans, s = [], None
    for i, f in enumerate(flags + [False]):
        if f and s is None:
            s = i
        elif not f and s is not None:
            if i - s + 4 >= min_len:
                spans.append((float(s), float(i + 3)))
            s = None
    return spans


def make(clip, out, mode="bleep", check_music=True, mute_music=False, words=None):
    info = probe(clip)
    if not info["has_audio"]:
        return {"out": None, "note": "no audio track"}
    words = words if words is not None else load_words(clip)
    prof = profanity_spans(words)
    music = music_spans(clip) if check_music else []
    report = {"profanity": [{"start": round(a, 2), "end": round(b, 2), "word": w[0] + "*" * (len(w) - 1)}
                            for a, b, w in prof],
              "music_review": [{"start": a, "end": b} for a, b in music], "word_timing": (
                  "approximate (from captions)" if words and words[0].get("approx") else "word-level" if words else "none"),
              "mode": mode}
    spans = [(a, b) for a, b, _ in prof] + ([(a, b) for a, b in music] if mute_music else [])
    if not spans:
        report["out"] = None
        report["note"] = "nothing to change" + ("; music spans flagged for review" if music else "")
        return report
    cond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in spans)
    pcond = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b, _ in prof) or "0"
    if mode == "bleep" and prof:
        fc = (f"[0:a]aresample=48000,volume=0:enable='{cond}'[m];"
              f"sine=frequency=1000:sample_rate=48000:duration={info['duration']:.3f},volume=0.18,"
              f"volume=0:enable='not({pcond})'[b];[m][b]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc = f"[0:a]aresample=48000,volume=0:enable='{cond}'[a]"
    ffmpeg(["-i", clip, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy"] + AUDIO_ENC +
           ["-movflags", "+faststart"], out)
    report["out"] = out
    return report
