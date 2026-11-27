"""TakeKash tour — the samurai guide walks viewers through TakeKash. 9:16, 38 s.
Builds on samurai.py (3D character, environment, text treatments) and adds: floating 3D holo
panels he presents, a tour-route tracker, karaoke subtitles synced to his narration, and
pointing gestures. Usage: python samurai2.py preview [t...] | render LO HI NAME"""
import json, math, os, random, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import scenekit as S
from scenekit import (W, H, FPS, RED, BONE, MUTED, DIM, NIGHT, PANEL, LINE, F, cl, seg, eo, eio, lerp, vlerp, norm,
                     Part, glow, label, brush_text, blade_text, forge_text)

import config
TTS = config.VOICE_DIR
VO = json.load(open(f'{TTS}/vo.json'))
TOXIC = (124, 255, 79)
# ---- timeline built from the narration's real durations
GAP = 0.6
VO_AT = {}; _t = 3.6
for _k in ('intro', 'clips', 'seo', 'overlay', 'editflow', 'gate', 'outro'):
    VO_AT[_k] = round(_t, 2); _t += VO[_k]['dur'] + GAP
END = {k: VO_AT[k] + VO[k]['dur'] for k in VO_AT}
DUR = round(END['outro'] + 1.8, 2)
SLASH = round(END['clips'] - 0.7, 2)                  # lands on "...cut it clean"
S.CHOREO = [(0.0, 'idle'), (SLASH - 1.3, 'idle'), (SLASH - 0.95, 'grip'), (SLASH - 0.6, 'draw'),
            (SLASH - 0.25, 'raise'), (SLASH, 'cut'), (SLASH + 0.7, 'kamae')]
_NEXT = {'clips': 'seo', 'seo': 'overlay', 'overlay': 'editflow', 'editflow': 'gate'}
def _win(k): return (VO_AT[k] - 0.3, VO_AT[_NEXT[k]] - 0.32)
STOPS = [('clips',) + _win('clips') + ((-0.85, 1.55, 0.35),),
         ('seo',) + _win('seo') + ((0.85, 1.55, 0.35),),
         ('overlay',) + _win('overlay') + ((-0.85, 1.55, 0.35),),
         ('editflow',) + _win('editflow') + ((0.85, 1.55, 0.35),)]
GATE0 = VO_AT['gate'] - 0.3; LOCK0 = VO_AT['outro'] - 0.4
ROUTE = ['WELCOME', 'CLIP STUDIO', 'SEO', 'OVERLAYS', 'EDITFLOW', '90+ GATE']
ROUTE_T = [3.6] + [w[1] for w in STOPS] + [GATE0]

_base_build = S.build_char
def build_char(t):
    pose, slashing = S.pose_at(t)
    # presenting gesture: left hand reaches toward the active panel
    for key, a, b, pos in STOPS:
        if key == 'clips' and t > 10.4: continue            # both hands busy with the sword
        w = eio(seg(t, a + 0.3, a + 0.8)) * (1 - eio(seg(t, b - 0.5, b)))
        if w > 0:
            sh = S.SHOULDER['L'].astype(float)
            tgt = np.array(pos) * 0.55 + np.array([0, -0.15, 0.25])
            d = norm(tgt - sh)
            hand = sh + d * 0.56; elbow = sh + d * 0.28 + np.array([0, -0.06, 0.04])
            pose['Lh'] = tuple(vlerp(pose['Lh'], hand, w)); pose['Le'] = tuple(vlerp(pose['Le'], elbow, w))
    breath = 0.008 * math.sin(t * 2.2)
    parts = [Part(p.V + [0, breath * (p.center[1] > 1.0), 0], p.F, p.col, p.emis, p.cull, p.center, p.gloss) for p in S.STATIC]
    drawn = pose['kd'] is not None
    parts += S.arm('R', pose['Re'], pose['Rh']) + S.arm('L', pose['Le'], pose['Lh'])
    parts += S.saya(drawn) + S.locs(t) + [S.cape(t)] + scarf(t)
    if drawn:
        parts += S.katana(pose['Rh'], pose['kd'], glow=1.0 if slashing else 0.25)
    return parts, pose, slashing
S.build_char = build_char

def scarf(t):
    """long red-black scarf wrapped at the neck, tails streaming in the wind"""
    P = [S.tube((0, 1.57, 0), (0, 1.64, 0), 0.115, 0.105, n=10, col=(70, 14, 12))]
    for side, ph in ((-1, 0.0), (1, 1.3)):
        nx, ny = 2, 10; V = []
        for j in range(ny + 1):
            v = j / ny
            for i in range(nx + 1):
                u = i / nx
                x = side * 0.06 + (u - 0.5) * 0.12 + side * v * 0.25 + 0.06 * math.sin(t * 3 + v * 5 + ph) * v
                y = 1.60 - v * 0.55 + 0.05 * math.sin(t * 2.6 + v * 4 + ph) * v
                z = -0.10 - v * 0.75 - 0.10 * math.sin(t * 3.4 - v * 6 + ph) * v
                V.append([x, y, z])
        Fc = [(j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i) for j in range(ny) for i in range(nx)]
        P.append(Part(V, Fc, col=(96, 18, 14), cull=False, center=(0, 1.3, -0.5)))
    return P

# ---------------- camera: (t, az, dist, height, ty, f, tx)
S.CAM_KEYS = None
def _cams():
    keys = ['clips', 'seo', 'overlay', 'editflow']
    bounds = [VO_AT[k] - 0.3 for k in keys] + [GATE0]
    C = [(0.0, 0.25, 5.4, 0.55, 1.2, 1.55, 0.0), (3.4, 0.12, 4.4, 0.75, 1.25, 1.55, 0.0),
         (3.41, -0.45, 1.55, 1.86, 1.76, 1.6, 0.0), (bounds[0] - 0.01, 0.30, 1.3, 1.80, 1.77, 1.6, 0.0)]
    a1, e1 = bounds[0], bounds[1] - 0.01
    C += [(a1, -0.14, 3.9, 1.3, 1.3, 1.55, -0.55), (SLASH - 1.31, 0.02, 3.7, 1.25, 1.3, 1.55, -0.55),
          (SLASH - 1.3, 0.45, 2.5, 1.15, 1.35, 1.5, 0.0), (e1, 0.30, 2.3, 1.05, 1.3, 1.5, 0.0)]
    for i, k in enumerate(keys[1:], 1):
        sx = 1 if STOPS[i][3][0] > 0 else -1
        C += [(bounds[i], 0.14 * sx, 3.9, 1.3, 1.3, 1.55, 0.55 * sx), (bounds[i + 1] - 0.01, -0.02 * sx, 3.7, 1.35, 1.3, 1.55, 0.55 * sx)]
    C += [(GATE0, -0.20, 3.1, 0.5, 1.2, 1.55, 0.0), (LOCK0 - 0.01, 0.15, 2.6, 0.6, 1.25, 1.6, 0.0),
          (LOCK0, 0.0, 5.0, 0.6, 1.3, 1.55, 0.0), (DUR, 0.08, 5.8, 0.7, 1.4, 1.55, 0.0)]
    return C
CAM = _cams()
def cam_at(t):
    for a, b in zip(CAM, CAM[1:]):
        if a[0] <= t < b[0]:
            k = eio((t - a[0]) / (b[0] - a[0]))
            return [lerp(x, y, k) for x, y in zip(a[1:], b[1:])]
    return list(CAM[-1][1:])

def shake_amt(t):
    s = 0.0
    for h, a in ((SLASH, 26), (SLASH + 0.05, 18), (GATE0 + 0.1, 12), (2.8, 6)):
        if 0 <= t - h < 0.25: s = max(s, a * (1 - (t - h) / 0.25) ** 2)
    return s

# ---------------- holo panels (2D cards mapped onto 3D quads)
PW_, PH_ = 760, 600
def card_base(title, idx):
    c = Image.new('RGBA', (PW_, PH_), (0, 0, 0, 0)); d = ImageDraw.Draw(c)
    d.rounded_rectangle([0, 0, PW_ - 1, PH_ - 1], 28, fill=(16, 19, 23, 225), outline=RED + (255,), width=4)
    d.rounded_rectangle([0, 0, PW_ - 1, 86], 28, fill=(30, 12, 12, 235))
    d.rectangle([0, 60, PW_, 86], fill=(30, 12, 12, 235))
    label(d, 36, 58, f'STOP 0{idx}', RED, 22, align='l', track=4)
    d.text((PW_ - 36, 60), title, font=F('Black', 34), fill=BONE, anchor='rs')
    return c, d

def panel_clips():
    c, d = card_base('CLIP STUDIO', 1)
    r = random.Random(2)
    for i in range(34):
        hgt = 20 + r.random() * 60 + (110 if i in (22, 23) else 0)
        x = 40 + i * 20
        d.rounded_rectangle([x, 250 - hgt / 2, x + 12, 250 + hgt / 2], 4, fill=(RED if hgt > 90 else (90, 98, 104)) + (255,))
    d.rounded_rectangle([470, 160, 560, 340], 10, outline=RED + (255,), width=3)
    label(d, 515, 150, 'CHAT x7', RED, 18)
    d.ellipse([60, 380, 220, 540], outline=(42, 49, 55, 255), width=14)
    d.arc([60, 380, 220, 540], -90, -90 + 338, fill=RED + (255,), width=14)
    d.text((140, 478), '94', font=F('Black', 58), fill=BONE, anchor='ms')
    d.rounded_rectangle([260, 420, 430, 490], 10, outline=TOXIC + (255,), width=4)
    d.text((345, 468), 'PASS', font=F('Black', 34), fill=TOXIC, anchor='ms')
    for i in range(3):
        x = 470 + i * 92
        d.rounded_rectangle([x, 380, x + 78, 545], 12, fill=(30, 34, 40, 255), outline=(70, 76, 82, 255), width=2)
        d.text((x + 39, 520), '9:16', font=F('Bold', 18), fill=MUTED, anchor='ms')
        d.rectangle([x + 10, 460, x + 68, 474], fill=RED + (255,))
    return c

def panel_seo():
    c, d = card_base('SEO GENERATOR', 2)
    label(d, 40, 140, 'TITLE', MUTED, 18, align='l')
    d.rounded_rectangle([36, 152, PW_ - 36, 222], 12, fill=(30, 34, 40, 255))
    d.text((56, 200), 'Insane 1v3 Apex Clutch for the Win', font=F('Bold', 30), fill=BONE, anchor='ls')
    label(d, 40, 268, 'TAGS', MUTED, 18, align='l')
    x, y = 40, 285
    for tg in ['#apexlegends', '#clutch', '#gaming', '#twitchstreamer', '#gtaxzombies', '#fyp']:
        w_ = F('Bold', 24).getlength(tg) + 34
        if x + w_ > PW_ - 36: x = 40; y += 60
        d.rounded_rectangle([x, y, x + w_, y + 46], 23, fill=(60, 16, 14, 255), outline=RED + (255,), width=2)
        d.text((x + 17, y + 32), tg, font=F('Bold', 24), fill=BONE, anchor='ls'); x += w_ + 12
    for i, p in enumerate(['TIKTOK', 'SHORTS', 'REELS', 'TWITCH']):
        x = 40 + i * 172
        d.rounded_rectangle([x, 470, x + 158, 540], 14, fill=(30, 34, 40, 255))
        d.text((x + 79, 515), p, font=F('Bold', 24), fill=BONE, anchor='ms')
        d.ellipse([x + 132, 476, x + 152, 496], fill=TOXIC + (255,))
    return c

def panel_overlay():
    c, d = card_base('OVERLAYS + SETUP', 3)
    d.rounded_rectangle([36, 120, 520, 400], 12, fill=(26, 30, 36, 255), outline=(70, 76, 82, 255), width=2)
    for i in range(6):
        d.polygon([(80 + i * 70, 400), (110 + i * 70, 260 + (i % 3) * 30), (140 + i * 70, 400)], fill=(40, 30, 34, 255))
    d.rounded_rectangle([52, 136, 130, 166], 6, fill=RED + (255,)); d.text((91, 159), 'LIVE', font=F('Bold', 20), fill=BONE, anchor='ms')
    d.rounded_rectangle([380, 300, 506, 388], 10, fill=(20, 24, 28, 255), outline=RED + (255,), width=3)
    d.text((443, 336), 'NEW', font=F('Bold', 18), fill=MUTED, anchor='ms'); d.text((443, 368), 'FOLLOWER', font=F('Black', 20), fill=BONE, anchor='ms')
    d.rounded_rectangle([540, 120, PW_ - 36, 400], 12, fill=(26, 30, 36, 255))
    for i, (u, m) in enumerate([('zed', 'W'), ('kay', 'CLIP IT'), ('paco', 'GG'), ('mara', 'NO WAY')]):
        d.text((556, 170 + i * 56), u, font=F('Bold', 20), fill=(255, 154, 61), anchor='ls')
        d.text((556 + F('Bold', 20).getlength(u) + 10, 170 + i * 56), m, font=F('Medium', 20), fill=BONE, anchor='ls')
    for i, t_ in enumerate(['ALERTS', 'SCENES', 'CHAT', 'SOCIALS']):
        x = 40 + i * 172
        d.rounded_rectangle([x, 440, x + 158, 520], 14, outline=RED + (255,), width=3)
        d.text((x + 79, 490), t_, font=F('Bold', 24), fill=BONE, anchor='ms')
    return c

def panel_editflow():
    c, d = card_base('EDITFLOW PRO', 4)
    cols = [('TO EDIT', ['Podcast ep. 42', 'Apex montage']), ('IN REVIEW', ['Brand ad v2', 'Shorts pack']), ('DELIVERED', ['Stream recap', 'Intro'])]
    for i, (h, cards) in enumerate(cols):
        x = 36 + i * 236
        d.rounded_rectangle([x, 120, x + 220, 470], 14, fill=(26, 30, 36, 255))
        label(d, x + 110, 158, h, BONE if i < 2 else TOXIC, 18)
        for j, cd in enumerate(cards):
            y = 186 + j * 128
            d.rounded_rectangle([x + 14, y, x + 206, y + 110], 10, fill=(36, 41, 48, 255), outline=(RED if i == 1 else (70, 76, 82)) + (255,), width=2)
            d.text((x + 28, y + 42), cd, font=F('Bold', 20), fill=BONE, anchor='ls')
            d.text((x + 28, y + 80), ['due Fri', 'rev 2 of 3', 'paid'][i], font=F('Medium', 18), fill=(TOXIC if i == 2 else MUTED), anchor='ls')
    for i, t_ in enumerate(['CLIENTS', 'DEADLINES', 'REVISIONS', 'INVOICES']):
        x = 40 + i * 172
        d.text((x + 79, 540), t_, font=F('Bold', 20), fill=MUTED, anchor='ms')
    return c

PANELS = {'clips': panel_clips(), 'seo': panel_seo(), 'overlay': panel_overlay(), 'editflow': panel_editflow()}

def _coeffs(dst, src):
    A = []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    return np.linalg.solve(np.array(A, float), np.array(src).reshape(8)).tolist()

def draw_panel(img, cam, key, pos, t, a, b):
    u = seg(t, a, a + 0.6); out = seg(t, b - 0.4, b)
    if u <= 0 or out >= 1: return
    card = PANELS[key].copy()
    # holographic build-in: scan wipe from top + scanlines + flicker
    reveal = eo(u)
    m = Image.new('L', card.size, 0); ImageDraw.Draw(m).rectangle([0, 0, PW_, PH_ * reveal], fill=255)
    al = ImageChops.multiply(card.getchannel('A'), m)
    fl = 0.85 + 0.15 * math.sin(t * 40) * (1 - reveal) + 0.05 * math.sin(t * 7)
    al = al.point(lambda v: int(v * fl * (1 - out)))
    card.putalpha(al)
    cd = ImageDraw.Draw(card)
    for yy in range(0, PH_, 6): cd.line([(0, yy), (PW_, yy)], fill=(0, 0, 0, 40))
    if reveal < 1: cd.rectangle([0, PH_ * reveal - 4, PW_, PH_ * reveal + 4], fill=(255, 120, 90, 230))
    # world quad facing the camera (yaw only) with a slight inward tilt so it reads as 3D
    p = np.array(pos, float)
    to_cam = cam.eye - p; to_cam[1] = 0; nrm = norm(to_cam)
    side = np.sign(p[0]) or 1
    yaw = math.atan2(nrm[0], nrm[2]) - side * 0.35
    right = np.array([math.cos(yaw), 0, -math.sin(yaw)]); up = np.array([0, 1.0, 0])
    sw, sh = 1.25, 0.99
    sc = 0.75 + 0.25 * eo(u)
    corners = [p - right * sw / 2 * sc + up * sh / 2 * sc, p + right * sw / 2 * sc + up * sh / 2 * sc,
               p + right * sw / 2 * sc - up * sh / 2 * sc, p - right * sw / 2 * sc - up * sh / 2 * sc]
    pts, z = cam.proj(corners)
    if np.any(z < 0.2): return
    src = [(0, 0), (PW_, 0), (PW_, PH_), (0, PH_)]
    warped = card.transform((W, H), Image.PERSPECTIVE, _coeffs([tuple(q) for q in pts], src), Image.BICUBIC)
    edge = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(edge).polygon([tuple(q) for q in pts], outline=RED + (int(200 * (1 - out)),))
    img.alpha_composite(glow(edge, 16, 1.6))
    img.alpha_composite(warped)
    # light beam from his hand to the panel
    hand = cam.proj([[0.62, 1.30, 0.20]])[0][0]
    beam = Image.new('RGBA', (W, H), (0, 0, 0, 0)); bd = ImageDraw.Draw(beam)
    c0 = tuple(pts.mean(0))
    bd.polygon([tuple(hand), tuple(pts[0]), tuple(pts[3])] if side > 0 else [tuple(hand), tuple(pts[1]), tuple(pts[2])],
               fill=RED + (int(28 * reveal * (1 - out)),))
    img.alpha_composite(beam.filter(ImageFilter.GaussianBlur(6)))

# ---------------- tour route tracker + karaoke subtitles
def route(img, t):
    if t < 3.6 or t > LOCK0: return
    a = eo(seg(t, 3.6, 4.0)) * (1 - seg(t, LOCK0 - 0.4, LOCK0))
    idx = 0
    for i, (st) in enumerate(ROUTE_T):
        if t >= st: idx = i
    d = ImageDraw.Draw(img)
    x0, x1, y = 120, W - 120, 262
    d.line([(x0, y), (x1, y)], fill=LINE + (int(255 * a),), width=3)
    prog = lerp(x0, x1, idx / (len(ROUTE) - 1))
    d.line([(x0, y), (prog, y)], fill=RED + (int(255 * a),), width=3)
    for i, nm in enumerate(ROUTE):
        x = lerp(x0, x1, i / (len(ROUTE) - 1))
        on = i <= idx
        r = 11 if i == idx else 7
        d.polygon([(x + r * math.cos(math.radians(60 * q + 30)), y + r * math.sin(math.radians(60 * q + 30))) for q in range(6)],
                  fill=(RED if on else NIGHT) + (int(255 * a),), outline=(RED if on else LINE) + (int(255 * a),))
    label(d, W / 2, 316, ROUTE[idx], BONE + (int(255 * a),), 26, track=6)

def subtitles(img, t):
    for key, at in VO_AT.items():
        dur = VO[key]['dur']
        if at - 0.1 <= t < at + dur + 0.5:
            words = VO[key]['text'].split()
            total = sum(len(w) + 1 for w in words)
            acc, cut = 0, []
            for w in words:
                acc += len(w) + 1; cut.append(at + dur * acc / total * 0.96)
            fn = F('Bold', 40)
            lines, cur = [], []
            for i, w in enumerate(words):
                test = ' '.join(x for x, _ in cur + [(w, 0)])
                if fn.getlength(test) > W - 170 and cur: lines.append(cur); cur = []
                cur.append((w, i))
            lines.append(cur)
            lines = lines[-3:]
            a = eo(seg(t, at - 0.1, at + 0.15)) * (1 - seg(t, at + dur + 0.2, at + dur + 0.5))
            box_h = 56 * len(lines) + 70
            y0 = 1500 - box_h
            l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l)
            d.rounded_rectangle([60, y0, W - 60, 1500], 22, fill=(10, 12, 15, int(205 * a)), outline=RED + (int(150 * a),), width=2)
            d.rectangle([60, y0 + 24, 66, 1476], fill=RED + (int(255 * a),))
            label(d, 96, y0 + 44, 'THE KING OF TAKEKASH', RED + (int(255 * a),), 20, align='l', track=4)
            for li, ln in enumerate(lines):
                x = 96; yy = y0 + 104 + li * 56
                for w, i in ln:
                    said = t >= (cut[i - 1] if i else at)
                    col = BONE if said else (90, 96, 102)
                    d.text((x, yy), w, font=fn, fill=col + (int(255 * a),), anchor='ls')
                    x += fn.getlength(w + ' ')
            img.alpha_composite(l)

# ---------------- frame
def frame(t, fi):
    az, dist, hgt, ty, f, tx = cam_at(t)
    s = shake_amt(t); r = random.Random(int(t * 1000))
    cam = S.Cam(az, dist, hgt, ty, f, roll=0.05 * math.sin(t * 0.6) if t > 3.4 else 0.0, shift=(r.uniform(-s, s), r.uniform(-s, s)), tx=tx)
    flashes = [(0.55, 0.12), (0.75, 0.08), (1.5, 0.1), (2.8, 0.25)]
    fl = max([1 - (t - a) / d_ for a, d_ in flashes if 0 <= t - a < d_] + [0])
    silhouette = 1.0 if t < 2.6 else (1 - eo(seg(t, 2.9, 3.5)))
    img = S.background(az, t, flash=fl * (1.0 if t < 3.5 else 0.6), moon=eo(seg(t, 2.6, 3.4)) * 0.95 + 0.05)
    if t < 3.5:
        S.bolt(img, t, 3, W * 0.72, (1 - (t - 2.8) / 0.25) if 2.8 <= t < 3.05 else 0)
        S.bolt(img, t, 9, W * 0.2, (1 - (t - 0.55) / 0.12) if 0.55 <= t < 0.67 else 0)
    char, em, pose, slashing = S.render_char(t, cam, silhouette=silhouette, light=1.0 + fl * 0.8)
    S.ground(img, cam, char, em, t)
    S.hex_shock(img, cam, t, GATE0 + 0.1)
    S.hex_shock(img, cam, t, SLASH + 0.05)
    # panels behind or in front of him by depth
    act = [(k, a, b, p) for k, a, b, p in STOPS if a <= t < b]
    behind = [x for x in act if np.linalg.norm(cam.eye - np.array(x[3])) > np.linalg.norm(cam.eye - np.array([0, 1.2, 0]))]
    for k, a, b, p in behind: draw_panel(img, cam, k, p, t, a, b)
    img.alpha_composite(char)
    for k, a, b, p in act:
        if (k, a, b, p) not in behind: draw_panel(img, cam, k, p, t, a, b)
    eye_on = eo(seg(t, 2.2, 2.5)) if t < 3.5 else 1.0
    e2 = em.copy(); e2.putalpha(e2.getchannel('A').point(lambda v: int(v * eye_on)))
    img.alpha_composite(glow(e2, 14, 2.2))
    if SLASH - 0.25 <= t < SLASH + 0.35:
        u = seg(t, SLASH - 0.25, SLASH + 0.02)
        tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); td = ImageDraw.Draw(tl)
        P0 = cam.proj([[-0.1, 2.9, 0.3]])[0][0]; P1 = cam.proj([[-1.0, 0.3, 1.1]])[0][0]
        pts = [tuple(vlerp(P0, P1, k * u)) for k in np.linspace(0, 1, 12)]
        fade_ = 1 - seg(t, SLASH, SLASH + 0.35)
        td.line(pts, fill=(255, 235, 225, int(255 * fade_)), width=int(26 * fade_) + 2)
        img.alpha_composite(glow(tl, 20, 1.6))
    S.rain(img, t, 1.0, fl)
    # copy
    if 3.4 <= t < STOPS[0][1]:
        a = 1 - seg(t, STOPS[0][1] - 0.4, STOPS[0][1])
        if a > 0.02:
            blade_text(img, [('WELCOME TO', BONE), ('TAKEKASH.', RED)], t, 3.7, 470, 116, 124, None)
    route(img, t)
    if GATE0 <= t < LOCK0:
        brush_text(img, 'ONLY 90+', t, GATE0 + 0.4, 560, 140, BONE)
        brush_text(img, 'LEAVES THE DOJO', t, GATE0 + 1.4, 720, 84, BONE, brush=False)
    subtitles(img, t)
    if t >= LOCK0:
        img.alpha_composite(Image.new('RGBA', (W, H), (8, 9, 11, int(150 * eo(seg(t, LOCK0, LOCK0 + 0.6))))))
        forge_text(img, t, LOCK0 + 0.3, 560, 770, 230)
        u = eo(seg(t, LOCK0 + 1.8, LOCK0 + 2.2))
        if u > 0:
            d = ImageDraw.Draw(img); fn = F('Bold', 52); ww = fn.getlength('takekash.com') + 90
            d.rounded_rectangle([W / 2 - ww / 2, 880, W / 2 + ww / 2, 976], 48, fill=RED + (int(255 * u),))
            d.text((W / 2, 946), 'takekash.com', font=fn, fill=BONE + (int(255 * u),), anchor='ms')
            d.text((W / 2, 1050), 'Clips · SEO · Overlays · EditFlow', font=F('Medium', 36), fill=MUTED + (int(255 * u),), anchor='ms')
            d.text((W / 2, 1115), '@gtaxzombies', font=F('Bold', 44), fill=BONE + (int(255 * u),), anchor='ms')
    split = None
    if SLASH <= t < SLASH + 0.8:
        k = seg(t, SLASH, SLASH + 0.15); back_ = seg(t, SLASH + 0.4, SLASH + 0.8)
        split = (70 * eo(k) * (1 - eio(back_)), 1.0 - back_)
    fl2 = 0.7 * (1 - seg(t, SLASH - 0.02, SLASH + 0.25)) if t >= SLASH - 0.02 else 0
    if LOCK0 <= t < LOCK0 + 0.2: fl2 = max(fl2, 0.5 * (1 - seg(t, LOCK0, LOCK0 + 0.2)))
    return S.finish(img, fi, fade=seg(t, DUR - 0.5, DUR), flash=fl2 + fl * 0.15, split=split)

def render(lo, hi, name):
    od = config.OUT; os.makedirs(od, exist_ok=True)
    out, tmp = f'{od}/{name}.mp4', f'{od}/{name}.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-tune', 'grain', '-maxrate', '16M', '-bufsize', '32M',
                          '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    for i in range(int(round(lo * FPS)), int(round(hi * FPS))):
        p.stdin.write(frame(i / FPS, i).tobytes())
    p.stdin.close()
    if p.wait() == 0: os.replace(tmp, out); print('ok', name)
    else: print('FAIL', name)

if __name__ == '__main__':
    if sys.argv[1] == 'preview':
        ts = [float(x) for x in sys.argv[2:]] or [2.85, 5.2, VO_AT['clips'] + 1.5, SLASH + 0.08, VO_AT['seo'] + 2, VO_AT['overlay'] + 2, VO_AT['editflow'] + 2, GATE0 + 2, DUR - 1.2]
        ims = [Image.fromarray(frame(x, 1)).resize((240, 427)) for x in ts]
        cols = 5
        sh = Image.new('RGB', (240 * cols, 427 * ((len(ims) + cols - 1) // cols)))
        for i, im in enumerate(ims): sh.paste(im, ((i % cols) * 240, (i // cols) * 427))
        sh.save(f'{config.OUT}/sheet_tour.jpg', quality=85); print('done')
    else:
        render(float(sys.argv[2]), float(sys.argv[3]), sys.argv[4])
