"""Podcast mode: 9:16 crop that follows whoever is talking.

Faces are found with YuNet at 4 fps and grouped into seats by horizontal
position. While there's speech (audio RMS above the clip's own baseline), the
seat whose mouth region moves most is the speaker. Choices are smoothed with
a 1.5 s minimum hold so the crop doesn't ping-pong, then the crop window is
driven by ffmpeg sendcmd (hard cut between speakers, like a real edit).
"""
import os
import tempfile

from .common import AUDIO_ENC, ROOT, VIDEO_ENC, StudioError, ffmpeg, probe, read_audio_mono, rms_envelope

YUNET = os.path.join(ROOT, "assets", "face_detection_yunet_2023mar.onnx")
FPS = 4.0
HOLD = 1.5


def analyze(video):
    import cv2
    import numpy as np
    from .game_events import _frames
    det, prev, rows = None, None, []
    for t, f in _frames(video, FPS, width=960):
        h, w = f.shape[:2]
        if det is None:
            det = cv2.FaceDetectorYN.create(YUNET, "", (w, h), 0.7)
        det.setInputSize((w, h))
        _, faces = det.detect(f)
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        found = []
        for fc in (faces if faces is not None else []):
            x, y, fw, fh = [float(v) for v in fc[:4]]
            mx0, my0 = int(x + fw * 0.2), int(y + fh * 0.62)
            mx1, my1 = int(x + fw * 0.8), int(y + fh * 0.98)
            motion = 0.0
            if prev is not None and mx1 > mx0 and my1 > my0:
                a = g[max(0, my0):min(h, my1), max(0, mx0):min(w, mx1)].astype(np.float32)
                b = prev[max(0, my0):min(h, my1), max(0, mx0):min(w, mx1)].astype(np.float32)
                if a.size and a.shape == b.shape:
                    motion = float(np.abs(a - b).mean())
            found.append({"cx": (x + fw / 2) / w, "cy": (y + fh / 2) / h, "motion": motion})
        rows.append({"t": t, "faces": found})
        prev = g
    return rows


def assign_seats(rows, max_seats=3):
    xs = sorted(f["cx"] for r in rows for f in r["faces"])
    if not xs:
        return []
    seats = [[xs[0]]]
    for x in xs[1:]:
        if x - seats[-1][-1] > 0.12:
            seats.append([x])
        else:
            seats[-1].append(x)
    seats = sorted(seats, key=len, reverse=True)[:max_seats]
    return sorted(sum(s) / len(s) for s in seats)


def choose(rows, seats, speech):
    """speech: list[bool] aligned to rows. Returns [(t, seat_index)] change points."""
    if not seats:
        return []
    motion = [[0.0] * len(seats) for _ in rows]
    for i, r in enumerate(rows):
        for f in r["faces"]:
            k = min(range(len(seats)), key=lambda j: abs(seats[j] - f["cx"]))
            motion[i][k] = max(motion[i][k], f["motion"])
    win = int(FPS)            # 1 s smoothing
    cur, since, out = None, -1e9, []
    for i, r in enumerate(rows):
        lo = max(0, i - win)
        sm = [sum(m[k] for m in motion[lo:i + 1]) for k in range(len(seats))]
        cand = max(range(len(seats)), key=lambda k: sm[k]) if speech[i] and max(sm) > 0 else cur
        if cand is None:
            cand = 0
        if cand != cur and (cur is None or r["t"] - since >= HOLD):
            cur, since = cand, r["t"]
            out.append((round(r["t"], 2), cand))
    return out


def make(video, out, plan=None):
    info = probe(video)
    W, H = info["width"], info["height"]
    if plan is None:
        if not os.path.exists(YUNET):
            raise StudioError("face model missing")
        rows = analyze(video)
        seats = assign_seats(rows)
        if not seats:
            raise StudioError("no faces found — not a talking-head video")
        speech = [True] * len(rows)
        if info["has_audio"]:
            sr = 16000
            env = rms_envelope(read_audio_mono(video, sr), sr, 1 / FPS)
            base = sorted(env)[len(env) // 3] if len(env) else 0
            speech = [(env[i] > base * 1.6) if i < len(env) else False for i in range(len(rows))]
        changes = choose(rows, seats, speech)
        plan = {"seats": seats, "changes": changes}
    cw = int(H * 9 / 16) // 2 * 2
    xs = [int(min(max(0, s * W - cw / 2), W - cw)) for s in plan["seats"]]
    changes = plan["changes"] or [(0.0, 0)]
    cmd_path = tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False).name
    with open(cmd_path, "w") as f:
        for t, k in changes:
            f.write(f"{t:.2f} crop@c x {xs[k]};\n")
    x0 = xs[changes[0][1]]
    vf = f"sendcmd=f='{cmd_path}',crop@c=w={cw}:h={H}:x={x0}:y=0,scale=1080:1920,setsar=1"
    try:
        args = ["-i", video, "-vf", vf, "-map", "0:v"] + (["-map", "0:a"] + AUDIO_ENC if info["has_audio"] else [])
        ffmpeg(args + VIDEO_ENC + ["-movflags", "+faststart"], out)
    finally:
        os.remove(cmd_path)
    return {"out": out, "seats": plan["seats"], "cuts": len(changes), "changes": changes}
