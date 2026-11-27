"""TakeKash — 'The Cut' — original Black samurai, real 3D (low-poly, cel-lit), 9:16, 20 s.
New motion vocabulary vs. earlier pieces: orbiting 3D camera, lightning silhouette reveal,
katana-streak text reveal, diagonal screen-split slash, ground hex shockwave, ink-brush text,
forged-metal heat lockup with heat shimmer, rain + wet-ground reflections.
Usage: python samurai.py preview | render LO HI NAME"""
import math, os, random, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

W, H, FPS = 1080, 1920, 30
SS = 2                                   # supersample for the character
HERE = os.path.dirname(os.path.abspath(__file__))  # fonts live in ./fonts
NIGHT = (14, 17, 20); PANEL = (23, 28, 32); LINE = (42, 49, 55)
RED = (232, 69, 47); BONE = (244, 245, 242); MUTED = (154, 163, 169); DIM = (92, 102, 109)
SKIN = (92, 58, 38); SKIN_D = (60, 36, 24)
LACQ = (22, 24, 29); CLOTH = (28, 30, 38); REDL = (120, 26, 20); GOLDW = (196, 176, 140); STEEL = (205, 212, 220)

_fc = {}
def F(w, s):
    k = (w, s)
    if k not in _fc:
        if w == 'mono':
            f = ImageFont.truetype(HERE + '/fonts/JetBrainsMono.ttf', s)
            try: f.set_variation_by_axes([600])
            except Exception: pass
        elif w == 'jp':
            f = ImageFont.truetype(os.environ.get('MOTION_CJK_FONT', '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc'), s, index=0)
        else:
            f = ImageFont.truetype(HERE + f'/fonts/Poppins-{w}.ttf', s)
        _fc[k] = f
    return _fc[k]

def cl(x, a=0.0, b=1.0): return max(a, min(b, x))
def seg(t, a, b): return cl((t - a) / (b - a))
def eo(x): x = cl(x); return 1 - (1 - x) ** 3
def eio(x): x = cl(x); return x * x * (3 - 2 * x)
def lerp(a, b, k): return a + (b - a) * k
def vlerp(a, b, k): return tuple(lerp(x, y, k) for x, y in zip(a, b))
def norm(v): v = np.asarray(v, float); return v / (np.linalg.norm(v) + 1e-9)

# ================================================================ geometry builders (world-space)
def rot_x(a): c, s = math.cos(a), math.sin(a); return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
def rot_y(a): c, s = math.cos(a), math.sin(a); return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
def rot_z(a): c, s = math.cos(a), math.sin(a); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])

class Part:
    def __init__(self, V, Fc, col, emis=0.0, cull=True, center=None, gloss=0.0):
        self.V = np.asarray(V, float); self.F = Fc; self.col = col; self.emis = emis; self.cull = cull
        self.center = np.asarray(center if center is not None else self.V.mean(0)); self.gloss = gloss

def box(size, pos, R=None, **kw):
    sx, sy, sz = [s / 2 for s in size]
    V = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)], float)
    if R is not None: V = V @ R.T
    V = V + pos
    Fc = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return Part(V, Fc, center=pos, **kw)

def frame_from(d, up=(0, 1, 0)):
    d = norm(d); u = np.asarray(up, float)
    if abs(np.dot(d, u)) > 0.95: u = np.array([1.0, 0, 0])
    x = norm(np.cross(u, d)); y = np.cross(d, x)
    return x, y, d

def tube(p0, p1, r0, r1, n=8, cap=True, **kw):
    p0 = np.asarray(p0, float); p1 = np.asarray(p1, float)
    x, y, d = frame_from(p1 - p0)
    V = []
    for p, r in ((p0, r0), (p1, r1)):
        for i in range(n):
            a = 2 * math.pi * i / n
            V.append(p + r * (math.cos(a) * x + math.sin(a) * y))
    Fc = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    if cap:
        Fc.append(tuple(range(n - 1, -1, -1))); Fc.append(tuple(range(n, 2 * n)))
    return Part(V, Fc, center=(p0 + p1) / 2, **kw)

def sphere(c, r, nu=12, nv=8, vmax=math.pi, sy=1.0, **kw):
    c = np.asarray(c, float); V = []
    for j in range(nv + 1):
        th = vmax * j / nv
        for i in range(nu):
            ph = 2 * math.pi * i / nu
            V.append(c + [r * math.sin(th) * math.cos(ph), r * math.cos(th) * sy, r * math.sin(th) * math.sin(ph)])
    Fc = []
    for j in range(nv):
        for i in range(nu):
            a = j * nu + i; b = j * nu + (i + 1) % nu
            Fc.append((a, b, b + nu, a + nu))
    return Part(V, Fc, center=c, **kw)

def ring(c, r0, r1, y0, y1, n=14, amin=0, amax=2 * math.pi, **kw):
    """open frustum band (helmet neck guard etc.)"""
    c = np.asarray(c, float); V = []
    for i in range(n + 1):
        a = amin + (amax - amin) * i / n
        V.append(c + [r0 * math.cos(a), y0, r0 * math.sin(a)])
        V.append(c + [r1 * math.cos(a), y1, r1 * math.sin(a)])
    Fc = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(n)]
    return Part(V, Fc, cull=False, center=c + [0, (y0 + y1) / 2, 0], **kw)

def mark_poly(n_arc=10):
    """bitten-hex outline in the 128 box (same geometry as the logo)"""
    HEX = [(64, 3), (117, 33.5), (117, 94.5), (64, 125), (11, 94.5), (11, 33.5)]
    (bx, by), br = (87.95, 22.54), 14.0
    A, B = np.array(HEX[0]), np.array(HEX[1])
    pts = [HEX[0]]
    # walk edge A->B, replacing the bite segment with an inward arc
    d = B - A; L_ = np.linalg.norm(d); u = d / L_; nrm = np.array([-u[1], u[0]])
    v = np.array([bx, by]) - A; al = v @ u; pe = v @ nrm; h = math.sqrt(max(0, br * br - pe * pe))
    q0 = A + u * (al - h); q1 = A + u * (al + h)
    a0 = math.atan2(q0[1] - by, q0[0] - bx); a1 = math.atan2(q1[1] - by, q1[0] - bx)
    # choose the arc going through the inside (toward hex centre)
    cands = []
    for sgn in (1, -1):
        span = (a1 - a0) % (2 * math.pi) if sgn == 1 else -((a0 - a1) % (2 * math.pi))
        mid = a0 + span / 2
        mp = np.array([bx + br * math.cos(mid), by + br * math.sin(mid)])
        cands.append((np.linalg.norm(mp - [64, 64]), span))
    span = min(cands)[1]
    pts.append(tuple(q0))
    for i in range(1, n_arc):
        a = a0 + span * i / n_arc
        pts.append((bx + br * math.cos(a), by + br * math.sin(a)))
    pts.append(tuple(q1))
    pts += HEX[1:]
    return [((x - 64) / 128, (64 - y) / 128) for x, y in pts]

MARK2D = mark_poly()

def plate2d(poly, scale, center, depth, R=None, **kw):
    """extruded 2D polygon (x,y) facing +z"""
    n = len(poly); V = []
    for z in (depth / 2, -depth / 2):
        for x, y in poly:
            V.append([x * scale, y * scale, z])
    V = np.array(V)
    if R is not None: V = V @ R.T
    V = V + center
    Fc = [tuple(range(n)), tuple(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        Fc.append((i, n + i, n + (i + 1) % n, (i + 1) % n))
    return Part(V, Fc, center=center, **kw)

# ================================================================ the samurai
def static_parts():
    P = []
    for sx in (-1, 1):
        P.append(box((0.13, 0.08, 0.30), (sx * 0.15, 0.04, 0.05), col=LACQ))                       # feet
        P.append(tube((sx * 0.15, 0.08, 0), (sx * 0.14, 0.95, 0), 0.24, 0.15, n=10, col=CLOTH))     # hakama
    for k in range(7):                                                                              # kusazuri
        a = -math.pi / 2 + (k - 3) * 0.42
        R = rot_y(-a - math.pi / 2) @ rot_x(-0.25)
        pos = (0.29 * math.cos(a), 0.84, 0.29 * -math.sin(a) * -1)
        pos = (0.28 * math.cos(a + math.pi), 0.84, 0.28 * math.sin(a + math.pi))
        P.append(box((0.2, 0.32, 0.035), pos, R=rot_y(-(a + math.pi) + math.pi / 2) @ rot_x(0.22),
                     col=REDL if k % 2 else LACQ, gloss=0.5))
    for k in range(5):                                                                              # back skirt
        a = (k - 2) * 0.42
        pos = (0.27 * math.sin(a), 0.84, -0.24 * math.cos(a))
        P.append(box((0.2, 0.32, 0.035), pos, R=rot_y(a) @ rot_x(-0.22), col=LACQ if k % 2 else REDL))
    P.append(tube((0, 0.95, 0), (0, 1.03, 0), 0.25, 0.25, n=12, col=REDL))                          # obi cord
    P.append(tube((0, 1.0, 0), (0, 1.22, 0), 0.24, 0.27, n=10, col=LACQ, gloss=0.6))               # waist do
    P.append(tube((0, 1.2, 0), (0, 1.55, 0), 0.28, 0.31, n=10, col=LACQ, gloss=0.7))               # chest do
    for y in (1.27, 1.36, 1.45):                                                                    # lacing bands
        P.append(tube((0, y, 0), (0, y + 0.012, 0), 0.292 + (y - 1.27) * 0.08, 0.292 + (y - 1.27) * 0.08, n=10, col=REDL, cap=False))
    P.append(plate2d(MARK2D, 0.2, (0, 1.40, 0.305), 0.02, col=RED, emis=0.3))                     # chest crest
    for sx in (-1, 1):                                                                              # sode
        for i in range(3):
            R = rot_z(sx * (0.75 + i * 0.06))
            P.append(box((0.22 + i * 0.02, 0.05, 0.30), (sx * (0.36 + i * 0.035), 1.50 - i * 0.07, 0.0), R=R,
                         col=REDL if i == 2 else LACQ, gloss=0.6))
    P.append(tube((0, 1.55, 0), (0, 1.66, 0), 0.07, 0.065, n=8, col=SKIN))                          # neck
    P.append(sphere((0, 1.77, 0), 0.118, sy=1.15, col=SKIN))                                         # head
    P.append(box((0.03, 0.05, 0.04), (0, 1.765, 0.115), col=SKIN_D))                                  # nose
    P.append(sphere((0, 1.705, 0.045), 0.088, nu=10, nv=6, sy=0.85, col=(22, 16, 13)))                # full beard
    P.append(box((0.12, 0.022, 0.03), (0, 1.735, 0.112), col=(22, 16, 13)))                           # moustache
    for sx in (-1, 1):
        P.append(box((0.045, 0.014, 0.02), (sx * 0.043, 1.792, 0.112), col=(255, 70, 45), emis=1.0))  # eyes
        P.append(box((0.06, 0.014, 0.02), (sx * 0.045, 1.818, 0.113), R=rot_z(-sx * 0.25), col=(20, 14, 12)))  # brows
    P.append(box((0.24, 0.06, 0.08), (0, 1.62, 0.07), col=LACQ, gloss=0.6))                           # nodowa (throat guard)
    P.append(sphere((0, 1.83, 0), 0.155, nu=14, nv=6, vmax=math.pi / 2, col=LACQ, gloss=0.8))        # kabuto bowl
    P.append(ring((0, 0, 0), 0.165, 0.24, 1.82, 1.70, amin=math.pi / 2 + 0.95, amax=math.pi / 2 + 2 * math.pi - 0.95, n=12, col=LACQ))
    P.append(ring((0, 0, 0), 0.24, 0.30, 1.70, 1.60, amin=math.pi / 2 + 1.05, amax=math.pi / 2 + 2 * math.pi - 1.05, n=12, col=REDL))
    for sx in (-1, 1):                                                                              # fukigaeshi
        P.append(box((0.10, 0.08, 0.02), (sx * 0.18, 1.83, 0.10), R=rot_y(sx * 0.9) @ rot_z(sx * 0.3), col=REDL))
    P.append(plate2d(MARK2D, 0.24, (0, 2.04, 0.11), 0.018, R=rot_x(-0.12), col=RED, emis=0.9))        # maedate crest
    P.append(box((0.018, 0.08, 0.018), (0, 1.96, 0.12), col=GOLDW))                                  # crest stem
    return P

STATIC = static_parts()
SHOULDER = {'R': np.array([-0.30, 1.50, 0.0]), 'L': np.array([0.30, 1.50, 0.0])}

def arm(side, elbow, hand):
    s = SHOULDER[side]; e = np.asarray(elbow); h = np.asarray(hand)
    return [tube(s, e, 0.075, 0.065, n=8, col=LACQ, gloss=0.4),
            tube(e, h - norm(h - e) * 0.04, 0.066, 0.058, n=8, col=LACQ, gloss=0.5),
            tube(e - norm(h - e) * 0.02, e + norm(h - e) * 0.08, 0.075, 0.075, n=8, col=REDL),
            sphere(h, 0.055, nu=8, nv=6, col=SKIN)]

def katana(hand, d, glow=0.0):
    hand = np.asarray(hand); d = norm(d)
    x, y, _ = frame_from(d)
    parts = [tube(hand - d * 0.13, hand + d * 0.12, 0.02, 0.02, n=6, col=GOLDW),
             tube(hand + d * 0.12, hand + d * 0.135, 0.055, 0.055, n=10, col=LACQ)]
    p0 = hand + d * 0.135; p1 = hand + d * 0.95
    w = 0.03; th = 0.006
    V = [p0 + x * w / 2 + y * th, p0 - x * w / 2 + y * th, p1 - x * w * 0.1, p1 + x * w / 2 + y * th,
         p0 + x * w / 2 - y * th, p0 - x * w / 2 - y * th, p1 - x * w * 0.1 - y * 0.0, p1 + x * w / 2 - y * th]
    Fc = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 3, 7, 4), (1, 5, 6, 2)]
    parts.append(Part(V, Fc, col=STEEL if glow < 0.5 else (255, 200, 190), emis=0.35 + 0.65 * glow, cull=False,
                      center=(p0 + p1) / 2, gloss=1.0))
    return parts

def saya(drawn):
    a = np.array([0.20, 1.00, 0.20]); b = np.array([0.30, 0.78, -0.62])
    P = [tube(a, b, 0.03, 0.026, n=6, col=LACQ, gloss=0.8), tube(a + (b - a) * 0.15, a + (b - a) * 0.18, 0.033, 0.033, n=6, col=REDL)]
    if not drawn:
        d = norm(a - b)
        P += [tube(a, a + d * 0.015, 0.05, 0.05, n=10, col=LACQ), tube(a + d * 0.015, a + d * 0.27, 0.021, 0.021, n=6, col=GOLDW)]
    return P

def locs(t):
    P = []
    for i in range(9):
        a = (i - 4) * 0.17
        root = np.array([0.075 * math.sin(a), 1.79, -0.11 * math.cos(a) - 0.02])
        sway = math.sin(t * 2.1 + i) * 0.03
        tip = root + [0.06 * math.sin(a) + sway, -0.36 - (i % 3) * 0.05, -0.10]
        P.append(tube(root, tip, 0.017, 0.012, n=5, col=(34, 24, 19), cap=False))
    return P

def cape(t, wind=1.0):
    nx, ny = 9, 8; V = []
    for j in range(ny + 1):
        v = j / ny
        for i in range(nx + 1):
            u = i / nx
            x = lerp(-0.34, 0.34, u) * (1 + 0.35 * v)
            ragged = 0.06 * math.sin(i * 2.7) if j == ny else 0
            y = 1.55 - v * (1.15 + ragged)
            z = -0.22 - v * 0.15 - wind * (0.12 * v * v + 0.08 * v * math.sin(t * 3.2 - v * 4 + u * 3))
            x += wind * 0.04 * v * math.sin(t * 2.4 + v * 3)
            V.append([x, y, z])
    Fc = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            Fc.append((a, a + 1, a + nx + 2, a + nx + 1))
    return Part(V, Fc, col=(58, 12, 12), cull=False, center=(0, 1.0, -0.6))

# ---- arm choreography (world-space keyframes) ----
POSES = {
    'idle':  dict(Re=(-0.24, 1.17, 0.16), Rh=(0.10, 1.03, 0.27), Le=(0.40, 1.22, 0.03), Lh=(0.27, 0.99, 0.16), kd=None),
    'grip':  dict(Re=(-0.20, 1.20, 0.22), Rh=(0.16, 1.05, 0.30), Le=(0.40, 1.22, 0.05), Lh=(0.25, 0.99, 0.18), kd=None),
    'draw':  dict(Re=(-0.36, 1.32, 0.28), Rh=(-0.20, 1.30, 0.55), Le=(0.40, 1.20, 0.05), Lh=(0.25, 0.99, 0.18), kd=(-0.55, 0.25, 0.80)),
    'raise': dict(Re=(-0.44, 1.78, 0.02), Rh=(-0.18, 2.06, 0.10), Le=(0.36, 1.25, 0.10), Lh=(0.22, 1.05, 0.25), kd=(0.25, 0.55, -0.80)),
    'cut':   dict(Re=(-0.44, 1.22, 0.24), Rh=(-0.42, 0.98, 0.52), Le=(0.38, 1.25, 0.12), Lh=(0.22, 1.05, 0.28), kd=(-0.45, -0.62, 0.64)),
    'kamae': dict(Re=(-0.38, 1.22, 0.22), Rh=(-0.30, 1.06, 0.48), Le=(0.36, 1.24, 0.12), Lh=(0.20, 1.04, 0.30), kd=(-0.30, -0.30, 0.90)),
}
CHOREO = [(0.0, 'idle'), (7.7, 'idle'), (8.1, 'grip'), (8.45, 'draw'), (8.75, 'raise'), (8.95, 'cut'), (9.6, 'kamae')]

def pose_at(t):
    for (ta, a), (tb, b) in zip(CHOREO, CHOREO[1:]):
        if ta <= t < tb:
            k = (t - ta) / (tb - ta)
            k = k ** 2.2 if b == 'cut' else eio(k)
            A, B = POSES[a], POSES[b]
            out = {key: vlerp(A[key], B[key], k) for key in ('Re', 'Rh', 'Le', 'Lh')}
            if A['kd'] is None and B['kd'] is None: out['kd'] = None
            elif A['kd'] is None: out['kd'] = B['kd'] if k > 0.15 else None
            else: out['kd'] = tuple(norm(vlerp(A['kd'], B['kd'], k)))
            return out, (b == 'cut' and k > 0.1)
    P = POSES[CHOREO[-1][1]]
    return dict(P), False

def build_char(t):
    pose, slashing = pose_at(t)
    breath = 0.008 * math.sin(t * 2.2)
    parts = [Part(p.V + [0, breath * (p.center[1] > 1.0), 0], p.F, p.col, p.emis, p.cull, p.center, p.gloss) for p in STATIC]
    drawn = pose['kd'] is not None
    parts += arm('R', pose['Re'], pose['Rh']) + arm('L', pose['Le'], pose['Lh'])
    parts += saya(drawn) + locs(t) + [cape(t)]
    if drawn:
        parts += katana(pose['Rh'], pose['kd'], glow=1.0 if slashing else (0.25 if t > 9.6 else 0.0))
    return parts, pose, slashing

# ================================================================ camera + raster
class Cam:
    def __init__(self, az, dist, height, ty, f=1.55, roll=0.0, shift=(0, 0), tx=0.0):
        self.eye = np.array([tx + dist * math.sin(az), height, dist * math.cos(az)])
        self.target = np.array([tx, ty, 0.0])
        fw = norm(self.target - self.eye); rt = norm(np.cross(fw, [0, 1, 0])); up = np.cross(rt, fw)
        if roll:
            c, s = math.cos(roll), math.sin(roll); rt, up = rt * c + up * s, -rt * s + up * c
        self.fw, self.rt, self.up = fw, rt, up
        self.f = f * W; self.cx = W / 2 + shift[0]; self.cy = H * 0.5 + shift[1]

    def proj(self, P):
        d = np.asarray(P, float) - self.eye
        z = d @ self.fw
        z = np.maximum(z, 0.05)
        return np.stack([self.cx + self.f * (d @ self.rt) / z, self.cy - self.f * (d @ self.up) / z], -1), z

KEY = norm((-0.55, 0.75, 0.55)); RIM = norm((0.5, 0.35, -0.8)); RIM2 = norm((-0.7, 0.2, -0.6))

def render_char(t, cam, silhouette=0.0, light=1.0):
    parts, pose, slashing = build_char(t)
    polys = []
    for p in parts:
        pts, z = cam.proj(p.V)
        for fc in p.F:
            idx = list(fc)
            Vf = p.V[idx]
            n = np.cross(Vf[1] - Vf[0], Vf[2] - Vf[0])
            if np.linalg.norm(n) < 1e-12 and len(idx) > 3: n = np.cross(Vf[2] - Vf[0], Vf[3] - Vf[0])
            n = norm(n); c = Vf.mean(0)
            if np.dot(n, c - p.center) < 0: n = -n
            to_eye = cam.eye - c
            vis = np.dot(n, to_eye)
            if p.cull and vis <= 0: continue
            if not p.cull and vis < 0: n = -n
            depth = float(np.linalg.norm(to_eye))
            diff = max(0.0, float(n @ KEY))
            cel = 0.28 if diff < 0.2 else (0.62 if diff < 0.6 else 1.0)
            rim = max(0.0, float(n @ RIM)) ** 1.6 + 0.5 * max(0.0, float(n @ RIM2)) ** 2
            fres = (1 - abs(float(n @ norm(to_eye)))) ** 3
            base = np.array(p.col, float)
            col = base * (0.30 + 0.85 * cel * light) + np.array(RED) * (0.85 * rim + 0.35 * fres) * light
            if p.gloss:
                h = norm(KEY + norm(to_eye)); spec = max(0.0, float(n @ h)) ** 30 * p.gloss
                col += np.array([200, 215, 235]) * spec * light
            if p.emis: col = col * (1 - p.emis) + np.array(p.col, float) * p.emis * 1.25
            if silhouette > 0: col = col * (1 - silhouette) + np.array([4, 4, 6]) * silhouette
            polys.append((depth, [tuple(xy * SS) for xy in pts[idx]], tuple(int(v) for v in np.clip(col, 0, 255)), p.emis))
    polys.sort(key=lambda q: -q[0])
    img = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    em = Image.new('RGBA', (W * SS, H * SS), (0, 0, 0, 0)); ed = ImageDraw.Draw(em)
    for depth, pts, col, emis in polys:
        d.polygon(pts, fill=col + (255,))
        if emis > 0.5 and silhouette < 0.9: ed.polygon(pts, fill=col + (255,))
        elif emis > 0.5: ed.polygon(pts, fill=(255, 60, 40, 255))
    img = img.resize((W, H), Image.LANCZOS); em = em.resize((W, H), Image.BILINEAR)
    return img, em, pose, slashing

# ================================================================ environment
def _pano():
    PW = W * 4
    rs = random.Random(5)
    y = np.linspace(0, 1, H)[:, None]
    sky = np.array([6, 7, 10]) * (1 - y) + np.array([40, 12, 12]) * y
    pano = np.repeat(sky[:, None, :], PW, axis=1).astype(np.uint8)
    im = Image.fromarray(pano).convert('RGBA'); d = ImageDraw.Draw(im)
    # far mountains
    for layer, (col, base, amp) in enumerate([((22, 14, 18), 0.62, 0.16), ((14, 10, 13), 0.68, 0.10)]):
        pts = [(0, H)]
        for x in range(0, PW + 40, 40):
            yy = H * base - amp * H * (0.5 + 0.5 * math.sin(x * 0.0021 + layer * 2) * math.cos(x * 0.0007 + layer)) - rs.random() * 14
            pts.append((x, yy))
        pts.append((PW, H)); d.polygon(pts, fill=col + (255,))
    # pagoda silhouettes
    for px in (PW * 0.18, PW * 0.71):
        bx, by = px, H * 0.66
        for k in range(5):
            w = 150 - k * 22; hgt = 46
            yb = by - k * hgt
            d.polygon([(bx - w, yb), (bx + w, yb), (bx + w * 0.55, yb - 18), (bx - w * 0.55, yb - 18)], fill=(9, 8, 10, 255))
            d.rectangle([bx - w * 0.45, yb - hgt, bx + w * 0.45, yb - 18], fill=(9, 8, 10, 255))
            d.rectangle([bx - 5, yb - hgt + 10, bx + 5, yb - hgt + 18], fill=RED + (200,))
        d.rectangle([bx - 3, by - 5 * hgt - 60, bx + 3, by - 5 * hgt], fill=(9, 8, 10, 255))
    return im
PANO = _pano()
MOON_AZ = 0.0

def background(cam_az, t, flash=0.0, moon=1.0):
    PW = PANO.width
    off = int(((-cam_az / (2 * math.pi)) * PW + PW * 0.5 - W / 2) % (PW - W))
    bg = PANO.crop((off, 0, off + W, H)).copy()
    # red moon locked behind the samurai (relative to camera azimuth)
    ml = Image.new('RGBA', (W, H), (0, 0, 0, 0)); md = ImageDraw.Draw(ml)
    mx = W / 2 + (math.atan2(math.sin(MOON_AZ - cam_az), math.cos(MOON_AZ - cam_az))) * -900
    my = H * 0.33; r = 330
    for k in range(8, 0, -1):
        rr = r + k * 40; md.ellipse([mx - rr, my - rr, mx + rr, my + rr], fill=RED + (int(10 * moon),))
    md.ellipse([mx - r, my - r, mx + r, my + r], fill=(178, 44, 32, int(255 * moon)))
    # faint hex pattern on the moon (brand)
    for i in range(-4, 5):
        for j in range(-4, 5):
            cx_ = mx + i * 70 + (35 if j % 2 else 0); cy_ = my + j * 61
            if (cx_ - mx) ** 2 + (cy_ - my) ** 2 < (r - 20) ** 2:
                md.polygon([(cx_ + 30 * math.cos(math.radians(60 * q + 30)), cy_ + 30 * math.sin(math.radians(60 * q + 30))) for q in range(6)],
                           outline=(200, 60, 44, int(90 * moon)))
    bg.alpha_composite(ml.filter(ImageFilter.GaussianBlur(1)))
    if flash > 0:
        fl = Image.new('RGBA', (W, H), (200, 210, 255, int(200 * flash))); bg.alpha_composite(fl)
    return bg

def ground(img, cam, char, em, t, wet=1.0):
    """wet ground: dark plane + mirrored character + moon streak + rain ripples"""
    horizon = cam.proj([cam.eye + np.array([cam.fw[0], 0, cam.fw[2]]) * 200 * 1.0])[0][0][1]
    horizon = float(np.clip(horizon, H * 0.2, H * 0.98))
    feet = cam.proj([[0, 0, 0]])[0][0]
    g = Image.new('RGBA', (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
    for i, yy in enumerate(range(int(horizon), H, 4)):
        k = max(0.0, (yy - horizon) / max(1, H - horizon))
        c = vlerp((26, 12, 12), (7, 8, 10), k ** 0.6)
        gd.rectangle([0, yy, W, yy + 4], fill=tuple(int(v) for v in c) + (255,))
    img.alpha_composite(g)
    # reflection
    fy = int(feet[1])
    if 0 < fy < H:
        top = char.crop((0, 0, W, fy)).transpose(Image.FLIP_TOP_BOTTOM)
        top = top.resize((W, int(top.height * 0.9)), Image.BILINEAR)
        a = np.asarray(top.getchannel('A'), np.float32)
        fade = np.linspace(0.45, 0.0, a.shape[0])[:, None] * wet
        top.putalpha(Image.fromarray((a * fade).astype(np.uint8)))
        top = top.filter(ImageFilter.GaussianBlur(3))
        img.alpha_composite(top, (0, fy))
    # rain ripples
    rd = ImageDraw.Draw(img); rs = random.Random(int(t * 7))
    for i in range(28):
        rr = random.Random(i * 31 + int(t * 3))
        gx = rr.uniform(0, W); gy = rr.uniform(horizon + 10, H); ph = (t * 3 + i * 0.37) % 1
        s = (gy - horizon) / max(1, H - horizon)
        w_ = (6 + 40 * ph) * (0.3 + s); a = int(120 * (1 - ph) * s)
        rd.ellipse([gx - w_, gy - w_ * 0.22, gx + w_, gy + w_ * 0.22], outline=(150, 160, 180, a))
    return horizon, feet

def rain(img, t, amt=1.0, flash=0.0):
    l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l)
    for i in range(int(260 * amt)):
        r = random.Random(i * 7)
        depth = r.random()
        sp = 1600 + 1600 * depth; ln = 18 + 50 * depth
        x = (r.random() * (W + 300) + t * 220 * (0.5 + depth)) % (W + 300) - 150
        y = (r.random() * (H + 200) + t * sp) % (H + 200) - 100
        a = int((40 + 120 * depth) * (1 + 1.5 * flash))
        d.line([(x, y), (x - ln * 0.18, y - ln)], fill=(170, 180, 205, min(255, a)), width=1 if depth < 0.6 else 2)
    img.alpha_composite(l)

def bolt(img, t, seed, x0, alpha):
    if alpha <= 0: return
    l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l); r = random.Random(seed)
    x, y = x0, -20; pts = [(x, y)]
    while y < H * 0.55:
        y += r.uniform(40, 90); x += r.uniform(-60, 60); pts.append((x, y))
        if r.random() < 0.25:
            bx, by = x, y; br = [(bx, by)]
            for _ in range(3): bx += r.uniform(-70, 70); by += r.uniform(30, 70); br.append((bx, by))
            d.line(br, fill=(220, 225, 255, int(160 * alpha)), width=2)
    d.line(pts, fill=(240, 240, 255, int(255 * alpha)), width=4)
    img.alpha_composite(l.filter(ImageFilter.GaussianBlur(5))); img.alpha_composite(l)

def glow(layer, r=16, k=1.6):
    bb = layer.getbbox()
    if not bb: return layer
    m = r * 3
    x0, y0 = max(0, bb[0] - m), max(0, bb[1] - m); x1, y1 = min(layer.width, bb[2] + m), min(layer.height, bb[3] + m)
    g = layer.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(r))
    if k != 1: g.putalpha(g.getchannel('A').point(lambda v: min(255, int(v * k))))
    out = Image.new('RGBA', layer.size, (0, 0, 0, 0)); out.paste(g, (x0, y0)); out.alpha_composite(layer)
    return out

def hex_shock(img, cam, t, t0):
    u = seg(t, t0, t0 + 1.2)
    if u <= 0 or u >= 1: return
    l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l)
    for k, lag in ((0, 0), (1, 0.12)):
        uu = cl(u - lag)
        if uu <= 0: continue
        r = 0.4 + 4.0 * eo(uu)
        P = [(r * math.cos(math.radians(60 * q + 30)), 0.01, r * math.sin(math.radians(60 * q + 30))) for q in range(7)]
        pts, z = cam.proj(P)
        d.line([tuple(p) for p in pts], fill=RED + (int(255 * (1 - uu)),), width=max(2, int(10 * (1 - uu))))
    img.alpha_composite(glow(l, 12, 1.4))

# ================================================================ text treatments (new this piece)
def blade_text(img, lines, t, t0, y0, size, gap, col_fn):
    """each line is cut in by a katana streak sweeping across it"""
    l = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    for i, (txt, col) in enumerate(lines):
        ts = t0 + i * 0.32; u = seg(t, ts, ts + 0.22)
        if u <= 0: continue
        fn = F('Black', size); y = y0 + i * gap; w_ = fn.getlength(txt)
        tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(tl).text((W / 2, y), txt, font=fn, fill=col + (255,), anchor='ms')
        x_edge = W / 2 - w_ / 2 - 60 + (w_ + 160) * eo(u)
        m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).polygon([(0, 0), (x_edge + 40, 0), (x_edge - 40, H), (0, H)], fill=255)
        tl.putalpha(ImageChops.multiply(tl.getchannel('A'), m))
        shear = int((1 - eo(seg(t, ts + 0.15, ts + 0.5))) * 18)
        if shear: tl = tl.transform(tl.size, Image.AFFINE, (1, 0, -shear, 0, 1, 0))
        l.alpha_composite(tl)
        if 0 < u < 1:
            sd = ImageDraw.Draw(l)
            sd.line([(x_edge + 30, y - size * 0.95), (x_edge - 30, y + size * 0.25)], fill=(255, 245, 235, 255), width=6)
            for k in range(10):
                r = random.Random(int(t * 100) + k)
                sx, sy = x_edge + r.uniform(-20, 20), y - size * r.uniform(0, 0.8)
                sd.line([(sx, sy), (sx + r.uniform(20, 70), sy + r.uniform(-30, 30))], fill=(255, 140, 90, 220), width=2)
    img.alpha_composite(glow(l, 10, 0.9))

def brush_text(img, txt, t, t0, y, size, col, brush=True, dur=0.45):
    """ink-brush stroke paints a red band, the words are revealed by the same stroke"""
    u = seg(t, t0, t0 + dur)
    if u <= 0: return
    fn = F('Black', size); w_ = fn.getlength(txt)
    x0 = W / 2 - w_ / 2 - 40; x1 = W / 2 + w_ / 2 + 40
    xe = lerp(x0, x1, eo(u))
    m = Image.new('L', (W, H), 0); md = ImageDraw.Draw(m)
    r = random.Random(len(txt))
    x = x0
    while x < xe:
        rad = size * 0.62 + r.uniform(-8, 8)
        yy = y - size * 0.36 + math.sin(x * 0.02) * 6
        md.ellipse([x - rad * 0.6, yy - rad, x + rad * 0.6, yy + rad * 0.75], fill=255)
        x += 9
    # dry-brush streaks at the leading edge
    for k in range(14):
        yy = y - size * 0.9 + k * size * 0.12
        md.line([(xe - 6, yy), (xe + r.uniform(10, 50), yy + r.uniform(-3, 3))], fill=255, width=3)
    if brush:
        band = Image.new('RGBA', (W, H), (150, 28, 20, 255)); band.putalpha(m.point(lambda v: int(v * 0.85)))
        img.alpha_composite(band)
    tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(tl).text((W / 2, y), txt, font=fn, fill=col + (255,), anchor='ms')
    tl.putalpha(ImageChops.multiply(tl.getchannel('A'), m))
    img.alpha_composite(tl)

def forge_text(img, t, t0, y_take, y_kash, size):
    """TAKE / KASH heat up from white-hot metal and cool into brand colours, with heat shimmer"""
    u = seg(t, t0, t0 + 1.6)
    if u <= 0: return
    hot = [(255, 250, 235), (255, 196, 90), (255, 110, 40)]
    def heat(final, k):
        if k < 0.33: return vlerp(hot[0], hot[1], k / 0.33)
        if k < 0.66: return vlerp(hot[1], hot[2], (k - 0.33) / 0.33)
        return vlerp(hot[2], final, (k - 0.66) / 0.34)
    l = Image.new('RGBA', (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(l)
    fn = F('Black', size)
    a = int(255 * cl(u * 4))
    d.text((W / 2, y_take), 'TAKE', font=fn, fill=tuple(int(v) for v in heat(BONE, u)) + (a,), anchor='ms')
    d.text((W / 2, y_kash), 'KASH', font=fn, fill=tuple(int(v) for v in heat(RED, cl(u * 1.1))) + (a,), anchor='ms')
    amp = 9 * (1 - u)
    if amp > 0.5:
        arr = np.asarray(l).copy()
        for row in range(int(y_take - size), int(y_kash + size * 0.3), 2):
            if 0 <= row < H:
                arr[row:row + 2] = np.roll(arr[row:row + 2], int(amp * math.sin(row * 0.08 + t * 30)), axis=1)
        l = Image.fromarray(arr)
    img.alpha_composite(glow(l, 22, 0.6 + 1.0 * (1 - u)))

def label(d, x, y, txt, col, size, track=4, align='c'):
    fn = F('mono', size); w_ = sum(fn.getlength(c) for c in txt) + track * (len(txt) - 1)
    xx = x - w_ / 2 if align == 'c' else x
    for c in txt:
        d.text((xx, y), c, font=fn, fill=col, anchor='ls'); xx += fn.getlength(c) + track

# ================================================================ camera script
CAM_KEYS = [  # t, az, dist, height, target_y, f
    (0.0, 0.25, 6.2, 0.55, 1.15, 1.5),
    (3.5, 0.12, 5.0, 0.7, 1.15, 1.5),
    (3.51, -1.05, 4.3, 1.1, 1.05, 1.55),
    (7.9, 0.55, 3.7, 1.2, 1.1, 1.55),
    (7.91, 0.45, 3.0, 1.05, 1.3, 1.5),
    (9.6, 0.30, 2.8, 1.0, 1.25, 1.5),
    (9.61, -0.20, 3.6, 0.45, 1.15, 1.55),
    (13.5, 0.15, 3.0, 0.55, 1.2, 1.6),
    (13.51, 0.35, 1.25, 1.95, 1.86, 1.6),
    (16.4, -0.25, 1.05, 1.92, 1.88, 1.6),
    (16.41, 0.0, 5.6, 0.6, 1.25, 1.55),
    (20.0, 0.08, 6.4, 0.7, 1.35, 1.55),
]

def cam_at(t):
    for a, b in zip(CAM_KEYS, CAM_KEYS[1:]):
        if a[0] <= t < b[0]:
            k = eio((t - a[0]) / (b[0] - a[0]))
            v = [lerp(x, y, k) for x, y in zip(a[1:], b[1:])]
            return v
    return list(CAM_KEYS[-1][1:])

def shake_amt(t):
    s = 0.0
    for h, a in ((8.95, 26), (9.0, 18), (9.6, 10), (2.8, 6)):
        if 0 <= t - h < 0.25: s = max(s, a * (1 - (t - h) / 0.25) ** 2)
    return s

# ================================================================ frame
VIG = None
def finish(img, fi, fade=0.0, flash=0.0, split=None):
    global VIG
    a = np.asarray(img.convert('RGB'), np.float32)
    if VIG is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        VIG = np.clip(1 - 0.55 * (np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)) ** 1.8, 0.25, 1)[..., None]
    if split is not None:
        a = split_frame(a, *split)
    if flash > 0: a = a + (np.array([255, 235, 230], np.float32) - a) * flash
    a *= VIG
    a += np.random.RandomState(fi % 7).randn(H, W, 1).astype(np.float32) * 4
    if fade > 0: a *= (1 - fade)
    return np.clip(a, 0, 255).astype(np.uint8)

_SPLIT_MASK = None
def split_frame(a, amt, glowk):
    """diagonal katana cut: two halves slide apart along the cut line"""
    global _SPLIT_MASK
    if _SPLIT_MASK is None:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        # line from (0, 0.72H) to (W, 0.30H)
        x0, y0, x1, y1 = 0, H * 0.70, W, H * 0.32
        side = (x1 - x0) * (yy - y0) - (y1 - y0) * (xx - x0)
        _SPLIT_MASK = (side < 0, np.abs(side) / math.hypot(x1 - x0, y1 - y0))
    upper, dist = _SPLIT_MASK
    dx = int(amt * 0.9); dy = int(amt * 0.4)
    up = np.roll(np.roll(a, -dx, axis=1), -dy, axis=0)
    lo = np.roll(np.roll(a, dx, axis=1), dy, axis=0)
    out = np.where(upper[..., None], up, lo)
    gap = np.clip(1 - dist / (4 + amt * 0.6), 0, 1)[..., None] * glowk
    out = out * (1 - gap) + np.array([255, 235, 225], np.float32) * gap
    return out

def frame(t, fi):
    az, dist, hgt, ty, f = cam_at(t)
    s = shake_amt(t); r = random.Random(int(t * 1000))
    cam = Cam(az, dist, hgt, ty, f, roll=(0.08 if 3.5 <= t < 7.9 else 0.0) * math.sin(t * 0.6), shift=(r.uniform(-s, s), r.uniform(-s, s)))
    # lightning
    flashes = [(0.55, 0.12), (0.75, 0.08), (1.5, 0.1), (2.8, 0.25)]
    fl = max([1 - (t - a) / d_ for a, d_ in flashes if 0 <= t - a < d_] + [0])
    silhouette = 1.0 if t < 2.6 else (1 - eo(seg(t, 2.9, 3.5)))
    img = background(az, t, flash=fl * (1.0 if t < 3.5 else 0.6), moon=eo(seg(t, 2.6, 3.4)) * 0.95 + 0.05)
    if t < 3.5:
        bolt(img, t, 3, W * 0.72, (1 - (t - 2.8) / 0.25) if 2.8 <= t < 3.05 else 0)
        bolt(img, t, 9, W * 0.2, (1 - (t - 0.55) / 0.12) if 0.55 <= t < 0.67 else 0)
    char, em, pose, slashing = render_char(t, cam, silhouette=silhouette, light=1.0 + fl * 0.8)
    horizon, feet = ground(img, cam, char, em, t)
    hex_shock(img, cam, t, 9.0)
    img.alpha_composite(char)
    eye_on = eo(seg(t, 2.2, 2.5)) if t < 3.5 else 1.0
    if eye_on > 0:
        e2 = em.copy(); e2.putalpha(e2.getchannel('A').point(lambda v: int(v * eye_on)))
        img.alpha_composite(glow(e2, 14, 2.2))
    # slash trail
    if 8.75 <= t < 9.3:
        u = seg(t, 8.75, 9.05)
        tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); td = ImageDraw.Draw(tl)
        P0 = cam.proj([[-0.1, 2.9, 0.3]])[0][0]; P1 = cam.proj([[-1.0, 0.3, 1.1]])[0][0]
        pts = [tuple(vlerp(P0, P1, k * u)) for k in np.linspace(0, 1, 12)]
        fade_ = 1 - seg(t, 9.0, 9.3)
        td.line(pts, fill=(255, 235, 225, int(255 * fade_)), width=int(26 * fade_) + 2)
        img.alpha_composite(glow(tl, 20, 1.6))
    rain(img, t, 1.0, fl)
    d = ImageDraw.Draw(img)
    # ---------------- copy
    if 3.5 <= t < 7.95:
        a = eo(seg(t, 3.7, 4.1)) * (1 - seg(t, 7.6, 7.9))
        label(d, W / 2, 300, 'TAKEKASH  //  THE CUT', RED + (int(255 * a),), 28, track=8)
        jp = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(jp).text((W - 70, 360), '侍', font=F('jp', 150), fill=RED + (int(150 * a),), anchor='rt')
        img.alpha_composite(jp)
        if t < 7.6:
            blade_text(img, [('YOUR VOD', BONE), ('HIDES THE', BONE), ('PERFECT CUT.', RED)], t, 4.6, 520, 112, 118, None)
    if 9.6 <= t < 13.5:
        a = 1 - seg(t, 13.2, 13.5)
        for i, (txt, tt0) in enumerate([('WE FIND IT.', 9.95), ('WE CUT IT.', 10.9), ('WE POST IT.', 11.85)]):
            if a < 1:
                pass
            brush_text(img, txt, t, tt0, 420 + i * 150, 104, BONE if i < 2 else BONE)
        u = eo(seg(t, 12.6, 13.0)) * a
        if u > 0:
            d.text((W / 2, 900), 'chat-proven  ·  game-aware  ·  hook-first', font=F('Medium', 34), fill=MUTED + (int(255 * u),), anchor='ms')
    if 13.5 <= t < 16.4:
        a = eo(seg(t, 13.8, 14.2)) * (1 - seg(t, 16.1, 16.4))
        label(d, W / 2, 300, 'GTAXZOMBIES CLIP STUDIO', RED + (int(255 * a),), 28, track=6)
        brush_text(img, 'ONLY 90+ SURVIVES', t, 14.4, 1440, 74, BONE, dur=0.5)
    if t >= 16.4:
        img.alpha_composite(Image.new('RGBA', (W, H), (8, 9, 11, int(150 * eo(seg(t, 16.4, 17.0))))))
        forge_text(img, t, 16.7, 640, 850, 230)
        u = eo(seg(t, 18.0, 18.4))
        if u > 0:
            fn = F('Bold', 52); ww = fn.getlength('takekash.com') + 90
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([W / 2 - ww / 2, 960, W / 2 + ww / 2, 1056], 48, fill=RED + (int(255 * u),))
            d.text((W / 2, 1026), 'takekash.com', font=fn, fill=BONE + (int(255 * u),), anchor='ms')
            d.text((W / 2, 1130), 'Clips · Overlays · Stream setup', font=F('Medium', 36), fill=MUTED + (int(255 * u),), anchor='ms')
            d.text((W / 2, 1195), '@gtaxzombies', font=F('Bold', 44), fill=BONE + (int(255 * u),), anchor='ms')
    split = None
    if 8.97 <= t < 9.75:
        k = seg(t, 8.97, 9.12); back_ = seg(t, 9.35, 9.75)
        amt = 70 * eo(k) * (1 - eio(back_)); split = (amt, 1.0 - back_)
    fl2 = 0.7 * (1 - seg(t, 8.95, 9.2)) if t >= 8.95 else 0
    if 16.4 <= t < 16.6: fl2 = max(fl2, 0.5 * (1 - seg(t, 16.4, 16.6)))
    return finish(img, fi, fade=seg(t, 19.5, 20.0), flash=fl2 + fl * 0.15, split=split)

def render(lo, hi, name):
    od = f'{HERE}/out_sam'; os.makedirs(od, exist_ok=True)
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
        ts = [float(x) for x in sys.argv[2:]] or [2.85, 5.6, 8.8, 9.05, 11.0, 12.9, 14.8, 18.6]
        ims = [Image.fromarray(frame(x, 1)).resize((270, 480)) for x in ts]
        cols = 4
        sh = Image.new('RGB', (270 * cols, 480 * ((len(ims) + cols - 1) // cols)))
        for i, im in enumerate(ims): sh.paste(im, ((i % cols) * 270, (i // cols) * 480))
        sh.save(f'{HERE}/sheet_sam.jpg', quality=85); print('done')
    else:
        render(float(sys.argv[2]), float(sys.argv[3]), sys.argv[4])
