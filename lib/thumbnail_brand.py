#!/usr/bin/env python3
"""
lib/thumbnail_brand.py <thumb_path> <watermark_text> [logo_path]

Adds a text watermark (and optional logo image) to a generated
thumbnail — modifies the image in place. Text goes bottom-right by
default, semi-transparent box behind it for readability against any
background. Logo (if given a real, existing file path) goes top-left,
scaled to a reasonable corner size.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont


def find_font_file():
    for path in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(path):
            return path
    return None


def brand_thumbnail(thumb_path, watermark_text, logo_path=None):
    img = Image.open(thumb_path).convert("RGBA")
    width, height = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_file = find_font_file()
    font_size = max(24, width // 20)
    try:
        font = ImageFont.truetype(font_file, font_size) if font_file else ImageFont.load_default(size=font_size)
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), watermark_text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 12
    x = width - text_w - pad * 2 - 10
    y = height - text_h - pad * 2 - 10

    draw.rectangle([x, y, x + text_w + pad * 2, y + text_h + pad * 2],
                   fill=(0, 0, 0, int(255 * 0.6)))
    draw.text((x + pad, y + pad), watermark_text, font=font, fill=(255, 255, 255, 255))

    if logo_path and os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo_target_w = width // 6
        ratio = logo_target_w / logo.width
        logo = logo.resize((logo_target_w, int(logo.height * ratio)))
        overlay.paste(logo, (10, 10), logo)
    elif logo_path:
        print(f"warning: logo path '{logo_path}' doesn't exist — watermark text still applied, logo skipped",
              file=sys.stderr)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    result.save(thumb_path, quality=90)
    return True


def main():
    thumb_path = sys.argv[1]
    watermark_text = sys.argv[2]
    logo_path = sys.argv[3] if len(sys.argv) > 3 else None
    brand_thumbnail(thumb_path, watermark_text, logo_path)
    print("done")


if __name__ == "__main__":
    main()
