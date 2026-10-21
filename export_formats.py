#!/usr/bin/env python3
"""GtaxZombies clip studio: export every clip in 3 formats.

  9:16  1080x1920  Shorts, TikTok, Reels         (face-tracked crop)
  1:1   1080x1080  Instagram, Facebook, LinkedIn  (face-tracked crop)
  16:9  1920x1080  YouTube, X                     (full frame; blurred fill if the source isn't 16:9)

Usage:
  python3 export_formats.py SOURCE.mp4 clips.json [--out exports] [--formats 9x16,1x1,16x9]

clips.json is a list of the moments your pipeline already picked:
  [{"name": "clip1", "start": 12.5, "end": 41.0, "srt": "captions/clip1.srt"}]
"srt" is optional, with timings relative to the clip start. When present, captions
are burned into every format, sized for that format.

Needs ffmpeg built with libass (Homebrew's ffmpeg has it) and: pip install opencv-python
Face detection: YuNet model in assets/ on OpenCV 5.x, Haar cascade on 4.x.
"""
import os
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # hide harmless DNN backend warnings
import argparse, json, pathlib, shutil, subprocess, sys, tempfile

import cv2
import numpy as np

FORMATS = {
    "9x16": dict(w=1080, h=1920, ar=9 / 16, font=16, margin=70),
    "1x1": dict(w=1080, h=1080, ar=1.0, font=15, margin=24),
    "16x9": dict(w=1920, h=1080, ar=16 / 9, font=15, margin=20),
}
STEP = 0.5  # seconds between face samples
HERE = pathlib.Path(__file__).resolve().parent
MODEL = "haarcascade_frontalface_default.xml"
YUNET = "face_detection_yunet_2023mar.onnx"


def _find(name):
    for p in (HERE / "assets" / name, HERE / name):
        if p.exists():
            return p
    return None


def make_detector(w, h):
    """Return detect(bgr_img) -> [(x, y, w, h), ...].

    OpenCV 5.x removed CascadeClassifier from opencv-python, so prefer the YuNet
    DNN detector (assets/face_detection_yunet_2023mar.onnx, also more accurate)
    and fall back to the Haar cascade on OpenCV 4.x.
    """
    yunet = _find(YUNET)
    if yunet and hasattr(cv2, "FaceDetectorYN"):
        det = cv2.FaceDetectorYN.create(str(yunet), "", (w, h), 0.6, 0.3, 5000)

        def detect(img):
            _, faces = det.detect(img)
            return [] if faces is None else [tuple(float(v) for v in f[:4]) for f in faces]
        return detect
    haar = _find(MODEL)
    if haar is None and hasattr(cv2, "data"):
        p = pathlib.Path(cv2.data.haarcascades) / MODEL
        haar = p if p.exists() else None
    if haar and hasattr(cv2, "CascadeClassifier"):
        cascade = cv2.CascadeClassifier(str(haar))

        def detect(img):
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return [tuple(map(float, f)) for f in cascade.detectMultiScale(g, 1.1, 5, minSize=(30, 30))]
        return detect
    sys.exit(f"No face detector available. Put {YUNET} in {HERE / 'assets'}.")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    return s["width"], s["height"]


def frame_rate(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=avg_frame_rate", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True).stdout.strip()
    n, _, d = r.partition("/")
    return float(n) / float(d or 1) if float(d or 1) else 30.0


def has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=index", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(r.stdout.strip())


def face_track(src, start, end):
    """Return [(t_rel, cx, cy)] face centers sampled every STEP seconds (None where no face).

    Frames come from ffmpeg (frame-accurate seek, every k-th frame), not cv2 seeking:
    OpenCV's CAP_PROP_POS_MSEC lands on the wrong frame in H.264 files, which made
    the crop drift up to ~1 s away from the face.
    """
    W, H = probe(src)
    sw = 640
    sh = int(round(H * sw / W / 2)) * 2
    scale = sw / W
    fps = frame_rate(src)
    k = max(1, round(fps * STEP))  # every k-th decoded frame = one sample, at an exact time
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start}", "-to", f"{end}", "-i", str(src),
           "-vf", f"select='not(mod(n\\,{k}))',scale={sw}:{sh},format=bgr24",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    fsz = sw * sh * 3
    n = len(raw) // fsz
    frames = np.frombuffer(raw[: n * fsz], np.uint8).reshape(n, sh, sw, 3)
    detect = make_detector(sw, sh)
    cands = []
    for img in frames:
        faces = detect(np.ascontiguousarray(img))
        cands.append([((x + w / 2) / scale, (y + h / 2) / scale) for x, y, w, h in faces])
    return [(i * k / fps, *p) for i, p in enumerate(pick_track(cands, W))]


def pick_track(cands, W):
    """Follow ONE face across samples. When a frame has several detections (a second
    person, a poster, a false hit on a HUD), take the one nearest the face we were
    already following, not simply the biggest box. Seeded from the first frame with
    exactly one detection, then followed outward from there in both directions.
    A jump over 25% of the width counts as a miss."""
    si = next((i for i, c in enumerate(cands) if len(c) == 1), None)
    if si is None:
        si = next((i for i, c in enumerate(cands) if c), None)
    out = [(None, None)] * len(cands)
    if si is None:
        return out
    out[si] = cands[si][0]
    for order in (range(si + 1, len(cands)), range(si - 1, -1, -1)):
        prev = out[si]
        for i in order:
            best = min(cands[i], key=lambda p: abs(p[0] - prev[0]) + abs(p[1] - prev[1]), default=None)
            if best is not None and abs(best[0] - prev[0]) <= 0.25 * W:
                out[i] = prev = best
    return out


def smooth_track(pts, default_x, default_y):
    """Fill gaps with the nearest detection, then a 3-point moving average to kill jitter."""
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    if not any(v is not None for v in xs):
        return [(p[0], default_x, default_y) for p in pts]
    for arr in (xs, ys):
        last = next(v for v in arr if v is not None)
        for i, v in enumerate(arr):
            arr[i] = last if v is None else v
            last = arr[i]
    sm = []
    for i in range(len(xs)):
        lo, hi = max(0, i - 1), min(len(xs), i + 2)
        sm.append((pts[i][0], sum(xs[lo:hi]) / (hi - lo), sum(ys[lo:hi]) / (hi - lo)))
    return sm


def piecewise(keys):
    """ffmpeg expression that linearly interpolates (t, v) keyframes over time t."""
    if len(keys) == 1:
        return f"{keys[0][1]:.1f}"
    expr = f"{keys[-1][1]:.1f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:]))):
        seg = f"{v0:.1f}+({v1 - v0:.1f})*(t-{t0:.2f})/{t1 - t0:.2f}"
        expr = f"if(lt(t\\,{t1:.2f})\\,{seg}\\,{expr})"
    return expr


def crop_filter(W, H, ar, track):
    """Crop box with aspect `ar`, following the face horizontally (or vertically for tall sources)."""
    if W / H > ar:  # source wider than target: full height, move x
        cw, ch = int(H * ar) // 2 * 2, H
        keys = [(t, min(max(cx - cw / 2, 0), W - cw)) for t, cx, _ in track]
        return f"crop={cw}:{ch}:'{piecewise(keys)}':0"
    cw, ch = W, int(W / ar) // 2 * 2  # source taller than target: full width, move y
    keys = [(t, min(max(cy - ch / 2, 0), H - ch)) for t, _, cy in track]
    return f"crop={cw}:{ch}:0:'{piecewise(keys)}'"


def caption_filter(fmt):
    f = FORMATS[fmt]
    style = (f"Fontname=Arial,Bold=1,Fontsize={f['font']},PrimaryColour=&H00FFFFFF,"
             f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV={f['margin']}")
    return f",subtitles=c.srt:force_style='{style}'"


def export(src, clip, fmt, outdir, work, W, H, audio):
    f = FORMATS[fmt]
    start, end = float(clip["start"]), float(clip["end"])
    caps = caption_filter(fmt) if clip.get("srt") else ""
    src_ar = W / H
    if fmt == "16x9" and abs(src_ar - f["ar"]) < 0.02:
        vf = f"[0:v]scale={f['w']}:{f['h']}{caps}[v]"
    elif fmt == "16x9":
        vf = (f"[0:v]split[a][b];[a]scale={f['w']}:{f['h']}:force_original_aspect_ratio=increase,"
              f"crop={f['w']}:{f['h']},boxblur=30:2[bg];"
              f"[b]scale={f['w']}:{f['h']}:force_original_aspect_ratio=decrease[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2{caps}[v]")
    else:
        track = smooth_track(face_track(src, start, end), W / 2, H / 2)
        vf = f"[0:v]{crop_filter(W, H, f['ar'], track)},scale={f['w']}:{f['h']}{caps}[v]"
    out = pathlib.Path(outdir) / f"{clip['name']}_{fmt}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start}", "-to", f"{end}", "-i", str(src),
           "-filter_complex", vf, "-map", "[v]"]
    if audio:
        cmd += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out.resolve())]
    subprocess.run(cmd, check=True, cwd=work)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("clips")
    ap.add_argument("--out", default="exports")
    ap.add_argument("--formats", default="9x16,1x1,16x9")
    a = ap.parse_args()
    fmts = [x.strip() for x in a.formats.split(",")]
    bad = [x for x in fmts if x not in FORMATS]
    if bad:
        sys.exit(f"Unknown format(s): {bad}. Use 9x16, 1x1, 16x9.")
    src = pathlib.Path(a.source).resolve()
    clips_path = pathlib.Path(a.clips).resolve()
    clips = json.loads(clips_path.read_text())
    W, H = probe(src)
    audio = has_audio(src)
    pathlib.Path(a.out).mkdir(parents=True, exist_ok=True)
    for clip in clips:
        with tempfile.TemporaryDirectory() as work:
            if clip.get("srt"):
                srt = (clips_path.parent / clip["srt"]).resolve()
                if not srt.exists():
                    sys.exit(f"Missing captions file: {srt}")
                shutil.copy(srt, pathlib.Path(work) / "c.srt")
            for fmt in fmts:
                print("exported:", export(src, clip, fmt, a.out, work, W, H, audio))


if __name__ == "__main__":
    main()
