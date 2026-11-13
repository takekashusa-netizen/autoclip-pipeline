"""Best-frame thumbnails + three hook titles per clip.

Thumbnail: samples frames around the payoff (or across the clip), ranks them
by sharpness (Laplacian variance), contrast, brightness and face presence,
then renders 1280x720 (YouTube) and 1080x1920 (Shorts/TikTok cover) with a
big brand-styled headline. Titles: Claude via lib/generate_clip_metadata
when ANTHROPIC_API_KEY is set; otherwise transcript/event-based fallbacks,
clearly marked as such.
"""
import os
import re
import subprocess
import sys

from .common import BONE, NIGHT, RED, ROOT, StudioError, font, load_words, probe

sys.path.insert(0, os.path.join(ROOT, "lib"))


def _frame_at(video, t):
    import cv2
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-f", "image2pipe",
                        "-vcodec", "png", "-"], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    if r.returncode or not r.stdout:
        return None
    return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)


def best_frame(video, around=None, n=16):
    import cv2
    info = probe(video)
    d = info["duration"]
    if around is not None:
        ts = [min(d - 0.1, max(0.0, around - 2 + 4 * i / (n - 1))) for i in range(n)]
    else:
        ts = [d * (0.1 + 0.8 * i / (n - 1)) for i in range(n)]
    face = None
    yunet = os.path.join(ROOT, "assets", "face_detection_yunet_2023mar.onnx")
    best, best_s, best_t = None, -1, None
    for t in ts:
        f = _frame_at(video, t)
        if f is None:
            continue
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(cv2.resize(g, (640, int(640 * g.shape[0] / g.shape[1]))), cv2.CV_64F).var()
        contrast = g.std()
        bright = g.mean()
        s = min(sharp, 1500) / 15 + contrast * 0.8 - abs(bright - 120) * 0.3
        if os.path.exists(yunet):
            if face is None:
                face = cv2.FaceDetectorYN.create(yunet, "", (f.shape[1], f.shape[0]), 0.75)
            face.setInputSize((f.shape[1], f.shape[0]))
            _, faces = face.detect(f)
            if faces is not None and len(faces):
                s += 25
        if s > best_s:
            best, best_s, best_t = f, s, t
    if best is None:
        raise StudioError("could not read frames for thumbnail")
    return best, best_t


def _fit_cover(img, W, H):
    from PIL import Image
    iw, ih = img.size
    sc = max(W / iw, H / ih)
    img = img.resize((int(iw * sc + 0.5), int(ih * sc + 0.5)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def render(frame_bgr, headline, out_path, size=(1280, 720)):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFont
    W, H = size
    img = Image.fromarray(frame_bgr[:, :, ::-1])
    img = _fit_cover(img, W, H)
    img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.25)).enhance(1.12)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(H // 2):                                   # bottom gradient for legibility
        a = int(200 * (i / (H / 2)) ** 1.6)
        d.line([(0, H - H // 2 + i), (W, H - H // 2 + i)], fill=NIGHT + (a,))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    d = ImageDraw.Draw(img)
    words = headline.upper().split()
    fs = int(W * (0.11 if W > H else 0.12))
    while True:
        f = ImageFont.truetype(font("Black"), fs)
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if d.textlength(test, font=f) <= W * 0.9 or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        if len(lines) <= (2 if W > H else 3) or fs < 40:
            break
        fs = int(fs * 0.88)
    lh = int(fs * 1.02)
    y = H - int(H * 0.06) - lh * len(lines)
    for i, ln in enumerate(lines):
        col = RED if i == len(lines) - 1 else BONE
        d.text((W / 2, y + i * lh), ln, font=f, fill=col, anchor="ma", stroke_width=max(3, fs // 14), stroke_fill=(0, 0, 0))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img.convert("RGB").save(out_path, quality=92)
    return out_path


def _fallback_titles(text, labels):
    lab = (labels or [""])[0]
    hot = re.findall(r"[A-Za-z0-9']+", text)[:9]
    phrase = " ".join(hot[:6]).strip() or "this play"
    titles = []
    if lab:
        titles.append(re.sub(r"_", " ", lab).replace("|", "·")[:70].upper())
    titles.append(f"“{phrase}” \U0001F633")
    titles.append(f"Nobody expected this… {phrase}"[:80])
    titles.append(f"The clip chat begged me to post")
    return titles[:3]


def titles(clip, labels=None, platform="tiktok"):
    words = load_words(clip, allow_whisper=False)
    text = " ".join(w["word"] for w in words)
    if os.environ.get("ANTHROPIC_API_KEY") and text.strip():
        try:
            from generate_clip_metadata import generate_clip_metadata_from_text
            meta = generate_clip_metadata_from_text(text, platform=platform)
            opts = [meta.get("title")] + list(meta.get("alt_titles") or meta.get("title_options") or [])
            opts = [o for o in opts if o]
            if opts:
                while len(opts) < 3:
                    opts += _fallback_titles(text, labels)
                return {"source": "claude", "titles": opts[:3], "meta": meta}
        except Exception as e:  # fall through to the honest fallback
            return {"source": f"fallback (claude failed: {str(e)[:120]})", "titles": _fallback_titles(text, labels)}
    return {"source": "fallback (no ANTHROPIC_API_KEY or no transcript)", "titles": _fallback_titles(text, labels)}


def make(clip, out_dir, headline=None, around=None, labels=None):
    frame, t = best_frame(clip, around)
    tt = titles(clip, labels)
    head = headline or tt["titles"][0]
    head = re.sub(r"[\U0001F300-\U0001FAFF☀-➿“”\"]", "", head).strip()[:60] or "WATCH THIS"
    yt = render(frame, head, os.path.join(out_dir, "thumb_16x9.jpg"), (1280, 720))
    cover = render(frame, head, os.path.join(out_dir, "cover_9x16.jpg"), (1080, 1920))
    return {"frame_t": round(t, 2), "thumbnail": yt, "cover": cover, "titles": tt["titles"], "title_source": tt["source"]}
