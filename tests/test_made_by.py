import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from studio import made_by
from studio.common import probe


def test_mark_lands_on_vertical_clip(tmp_path):
    src, out = str(tmp_path / "c.mp4"), str(tmp_path / "c.final.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=540x960:d=1", "-f", "lavfi",
                    "-i", "sine=f=440:d=1", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
    r = made_by.make(src, out)
    assert os.path.exists(out) and probe(out)["has_audio"]
    from PIL import Image
    frame = str(tmp_path / "f.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-frames:v", "1", frame], check=True)
    im = Image.open(frame).convert("RGB"); x, y = r["pos"]
    region = [im.getpixel((xx, yy)) for xx in range(x, x + 200, 4) for yy in range(y, y + 30, 3)]
    assert any(p[0] > 200 and p[1] > 120 and p[2] < 90 for p in region)        # gold "TakeKash" pixels are there
