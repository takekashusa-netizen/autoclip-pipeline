"""Split-screen 9:16: facecam on top, gameplay below, brand-red divider.

Facecam box: pass --cam x,y,w,h (pixels, or 0-1 fractions), or let it find
the webcam by running the YuNet face detector (assets/) over sampled frames
and taking the region where a face shows up consistently near a corner.
"""
import os

from .common import AUDIO_ENC, RED_HEX, ROOT, VIDEO_ENC, StudioError, ffmpeg, probe

OUT_W, OUT_H = 1080, 1920
CAM_H = 640                      # top band; gameplay gets 1280
YUNET = os.path.join(ROOT, "assets", "face_detection_yunet_2023mar.onnx")


def parse_box(spec, w, h):
    vals = [float(v) for v in spec.split(",")]
    if len(vals) != 4:
        raise StudioError("--cam needs x,y,w,h")
    if all(v <= 1 for v in vals):
        vals = [vals[0] * w, vals[1] * h, vals[2] * w, vals[3] * h]
    return [int(v) for v in vals]


def detect_cam(video, samples=24):
    import cv2
    import numpy as np
    from .game_events import _frames
    info = probe(video)
    if not os.path.exists(YUNET):
        raise StudioError("face model missing: assets/face_detection_yunet_2023mar.onnx")
    fps = max(0.05, samples / max(1.0, info["duration"]))
    det = None
    hits = []
    for t, f in _frames(video, fps, width=960):
        h, w = f.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.7)
        det.setInputSize((w, h))
        _, faces = det.detect(f)
        if faces is not None:
            for fc in faces:
                x, y, fw, fh = fc[:4]
                hits.append((x / w, y / h, fw / w, fh / h))
    if len(hits) < 3:
        return None
    a = np.array(hits)
    cx, cy = a[:, 0] + a[:, 2] / 2, a[:, 1] + a[:, 3] / 2
    mx, my = float(np.median(cx)), float(np.median(cy))
    near = (abs(cx - mx) < 0.1) & (abs(cy - my) < 0.1)
    if near.mean() < 0.5:
        return None                    # faces wander around: not a fixed webcam
    fw = float(np.median(a[near, 2]))
    # a webcam box is typically ~3x the face width, at the cam aspect (1080:640)
    bw = min(0.45, fw * 3.2)
    bh = bw * info["width"] / info["height"] * CAM_H / OUT_W
    x0 = min(max(0.0, mx - bw / 2), 1 - bw)
    y0 = min(max(0.0, my - bh / 2), 1 - bh)
    return [int(x0 * info["width"]), int(y0 * info["height"]), int(bw * info["width"]), int(bh * info["height"])]


def make(clip, out, cam=None, game_focus=0.5):
    info = probe(clip)
    W, H = info["width"], info["height"]
    if isinstance(cam, str):
        cam = parse_box(cam, W, H)
    if cam is None:
        cam = detect_cam(clip)
        if cam is None:
            raise StudioError("no fixed facecam found — pass --cam x,y,w,h")
    cx, cy, cw, ch = cam
    # fit the cam crop to the band's aspect without stretching
    target = OUT_W / CAM_H
    if cw / ch > target:
        nw = int(ch * target)
        cx, cw = cx + (cw - nw) // 2, nw
    else:
        nh = int(cw / target)
        cy, ch = cy + (ch - nh) // 2, nh
    gh = OUT_H - CAM_H
    gw_src = int(H * OUT_W / gh)
    gx = int(min(max(0, W * game_focus - gw_src / 2), W - gw_src))
    fc = (f"[0:v]split=2[c][g];"
          f"[c]crop={cw}:{ch}:{cx}:{cy},scale={OUT_W}:{CAM_H},setsar=1[top];"
          f"[g]crop={gw_src}:{H}:{gx}:0,scale={OUT_W}:{gh},setsar=1[bot];"
          f"[top][bot]vstack=inputs=2,drawbox=x=0:y={CAM_H - 4}:w={OUT_W}:h=8:color=0x{RED_HEX}:t=fill[v]")
    args = ["-i", clip, "-filter_complex", fc, "-map", "[v]"]
    if info["has_audio"]:
        args += ["-map", "0:a"] + AUDIO_ENC
    ffmpeg(args + VIDEO_ENC + ["-movflags", "+faststart"], out)
    return {"out": out, "cam_box": [cx, cy, cw, ch], "game_crop_x": gx}
