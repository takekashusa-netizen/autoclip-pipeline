"""Shared helpers: ffmpeg/ffprobe wrappers, safe output writes, fonts, transcripts."""
import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FONTS = os.path.join(HERE, "fonts")

# Brand palette shared by TakeKash + GtaxZombies
NIGHT = (14, 17, 20)
PANEL = (23, 28, 32)
RED = (232, 69, 47)
BONE = (244, 245, 242)
MUTED = (154, 163, 169)
RED_HEX = "E8452F"

VIDEO_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
AUDIO_ENC = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000"]


class StudioError(RuntimeError):
    pass


def run(cmd, timeout=3600):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise StudioError(f"{os.path.basename(cmd[0])} failed ({r.returncode}): {r.stderr.strip()[-1200:]}")
    return r.stdout


def ffmpeg(args, out, timeout=3600):
    """Run ffmpeg writing to a temp name that keeps the extension, rename only on exit 0
    — a killed render can never leave a short file at the real path."""
    root, ext = os.path.splitext(out)
    tmp = f"{root}.tmp{ext}"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args + [tmp], timeout=timeout)
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return out


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", path])
    d = json.loads(out)
    info = {"duration": float(d.get("format", {}).get("duration", 0) or 0), "has_audio": False,
            "width": 0, "height": 0, "fps": 30.0}
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not info["width"]:
            info["width"], info["height"] = int(s["width"]), int(s["height"])
            num, den = s.get("r_frame_rate", "30/1").split("/")
            info["fps"] = float(num) / float(den or 1) if float(num) else 30.0
        elif s.get("codec_type") == "audio":
            info["has_audio"] = True
    if not info["width"]:
        raise StudioError(f"no video stream in {path}")
    return info


def font(weight="Bold"):
    p = os.path.join(FONTS, f"Poppins-{weight}.ttf")
    if not os.path.exists(p):
        raise StudioError(f"missing brand font {p}")
    return p


def ff_escape(text):
    """Escape text for an ffmpeg drawtext text= value."""
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def read_audio_mono(path, sr=16000, start=None, dur=None):
    """Decode audio to float32 mono numpy array (no librosa needed)."""
    import numpy as np
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=3600, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise StudioError(f"audio decode failed: {r.stderr.decode(errors='ignore')[-400:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def rms_envelope(audio, sr, hop_sec=0.1):
    import numpy as np
    hop = max(1, int(sr * hop_sec))
    n = len(audio) // hop
    if n == 0:
        return np.zeros(0)
    a = audio[: n * hop].reshape(n, hop)
    return np.sqrt((a ** 2).mean(axis=1) + 1e-12)


# ---------------------------------------------------------------- transcripts
_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _ts(s):
    h, m, sec, ms = _TS.search(s).groups()
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(path):
    cues = []
    blocks = re.split(r"\n\s*\n", open(path, encoding="utf-8-sig").read().strip())
    for b in blocks:
        lines = [l for l in b.strip().splitlines() if l.strip()]
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None:
            continue
        a, z = lines[ti].split("-->")
        cues.append({"start": _ts(a), "end": _ts(z), "text": "\n".join(lines[ti + 1:])})
    return cues


def fmt_srt_time(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{fmt_srt_time(c['start'])} --> {fmt_srt_time(c['end'])}\n{c['text']}\n\n")
    return path


def srt_to_words(cues):
    """Spread each cue's words across its time span by character length.
    Approximate — used only when no word-level timing exists."""
    words = []
    for c in cues:
        toks = re.findall(r"\S+", c["text"].replace("\n", " "))
        if not toks:
            continue
        total = sum(len(t) for t in toks)
        t = c["start"]
        span = c["end"] - c["start"]
        for tok in toks:
            d = span * len(tok) / total
            words.append({"start": t, "end": t + d, "word": tok, "approx": True})
            t += d
    return words


def find_srt(clip_path):
    d, name = os.path.split(clip_path)
    stem = re.sub(r"(\.final)?\.mp4$", "", name)
    for cand in (os.path.join(d, "captions", stem + ".srt"), os.path.join(d, "captions", stem + ".final.srt"),
                 os.path.join(d, stem + ".srt"), os.path.join(d, stem + ".final.srt")):
        if os.path.exists(cand):
            return cand
    return None


def load_words(clip_path, allow_whisper=True):
    """Word timings for a clip, best source first:
    <stem>.words.json  ->  faster-whisper (cached)  ->  SRT split (approximate)."""
    stem = re.sub(r"\.mp4$", "", clip_path)
    cache = stem + ".words.json"
    if os.path.exists(cache):
        return json.load(open(cache))
    if allow_whisper:
        try:
            from faster_whisper import WhisperModel  # noqa: F401
            model = WhisperModel(os.environ.get("STUDIO_WHISPER_MODEL", "small"), compute_type="int8")
            segs, _ = model.transcribe(clip_path, word_timestamps=True)
            words = [{"start": w.start, "end": w.end, "word": w.word.strip()} for s in segs for w in (s.words or [])]
            json.dump(words, open(cache, "w"))
            return words
        except ImportError:
            pass
    srt = find_srt(clip_path)
    if srt:
        return srt_to_words(parse_srt(srt))
    return []


def clip_stem(path):
    return re.sub(r"(\.final)?\.mp4$", "", os.path.basename(path))
