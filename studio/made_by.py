"""Made by TakeKash: the brand mark on every clip the studio ships.
Drawn with PIL into a transparent PNG and laid over with ffmpeg's overlay filter (works on ffmpeg builds without
drawtext). Placed top-left inside the platform safe zone (clear of TikTok/Reels/Shorts UI), scaled to the clip.
"""
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont

from .common import AUDIO_ENC, VIDEO_ENC, ffmpeg, font, probe

TEXT = "Made by TakeKash"
GOLD = (245, 166, 35, 255)


def mark_png(width, height, text=TEXT):
    """transparent PNG sized for a width x height clip: pill with 'Made by' + gold 'TakeKash'"""
    fs = max(18, int(min(width, height) * 0.032))
    f_reg, f_bold = ImageFont.truetype(font("Bold"), fs), ImageFont.truetype(font("Black"), fs)
    head, brand = text.rsplit(" ", 1) if " " in text else ("", text)
    probe_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w1 = probe_d.textlength(head + " ", font=f_reg) if head else 0
    w2 = probe_d.textlength(brand, font=f_bold)
    pad = int(fs * 0.55)
    W, H = int(w1 + w2 + 2 * pad), int(fs * 1.7)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], H // 2, fill=(0, 0, 0, 120))
    if head:
        d.text((pad, H / 2), head, font=f_reg, fill=(255, 255, 255, 215), anchor="lm")
    d.text((pad + w1, H / 2), brand, font=f_bold, fill=GOLD, anchor="lm")
    return im


def make(clip, out, text=TEXT):
    info = probe(clip)
    w, h = info["width"], info["height"]
    png = mark_png(w, h, text)
    x = int(w * 0.04)
    y = int(h * (130 / 1920) if h > w else h * 0.05)        # vertical: below the top UI band; landscape: 5 %
    fd, path = tempfile.mkstemp(suffix=".png"); os.close(fd)
    try:
        png.save(path)
        args = ["-i", clip, "-i", path, "-filter_complex", f"[0:v][1:v]overlay={x}:{y}:format=auto[v]", "-map", "[v]"]
        if info["has_audio"]:
            args += ["-map", "0:a", *AUDIO_ENC]
        ffmpeg(args + VIDEO_ENC, out)
    finally:
        os.remove(path)
    return {"out": out, "text": text, "pos": [x, y]}
