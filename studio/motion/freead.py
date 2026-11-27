"""KASH episode 2: "Your first ad is on us" (TakeKash free ad offer), 9:16, 30 fps.
New motion vs the tour: katana split-reveal, hanko-stamp steps, phone that builds an ad live,
48H counter + NO CARD stamp slam, enso CTA. Uses the KASH art cutouts (MOTION_HOME/assets4).
Usage: python3 freead.py <vo_dir> <out_dir> [lo hi]      (renders frames lo..hi to out_dir/part_<lo>.mp4)
       python3 freead.py <vo_dir> <out_dir> --stills t1 t2 ...
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, 'fonts')
ASSETS = os.path.join(os.environ.get('MOTION_HOME', os.path.join(os.path.dirname(os.path.dirname(HERE)), 'motion_work')), 'assets4')
VO_DIR = sys.argv[1] if len(sys.argv) > 1 else '.'
OUT = sys.argv[2] if len(sys.argv) > 2 else '.'

NIGHT = (12, 13, 16); RED = (226, 38, 43); REDD = (120, 16, 20); BONE = (238, 231, 214); MUTED = (150, 146, 138); INK = (14, 14, 16)

_fc = {}
def F(w, s):
    k = (w, s)
    if k not in _fc: _fc[k] = ImageFont.truetype(os.path.join(FD, f'Poppins-{w}.ttf'), s)
    return _fc[k]

def cl(x, a=0.0, b=1.0): return max(a, min(b, x))
def seg(t, a, b): return cl((t - a) / (b - a))
def eo(x): x = cl(x); return 1 - (1 - x) ** 3
def eio(x): x = cl(x); return x * x * (3 - 2 * x)
def back(x, s=1.70158): x = cl(x); x -= 1; return x * x * ((s + 1) * x + s) + 1
def lerp(a, b, k): return a + (b - a) * k

# ---------------- timeline from the voice
VO = json.load(open(os.path.join(VO_DIR, 'vo.json')))
AT = {'hook': 0.9, 'steps': 3.75, 'build': 7.75, 'deliver': 14.75, 'cta': 17.45}
END = {k: AT[k] + VO[k]['dur'] for k in AT}
DUR = round(END['cta'] + 1.9, 2)
SLASH = AT['hook'] + 0.85                       # cut lands on "first ad"
T_B, T_C, T_D, T_E = 3.55, 7.55, 14.55, 17.25    # scene starts (ink wipe 0.35 s before each)

# ---------------- assets (pre-scaled once)
def cut(name, h):
    im = Image.open(os.path.join(ASSETS, name + '.png')).convert('RGBA')
    return im.resize((int(im.width * h / im.height), h), Image.LANCZOS)

A = {'slash': cut('slash', 1560), 'three': cut('three', 1640), 'front': cut('front', 1700),
     'head_n': cut('head_n', 600),
     'head_shout': cut('head_shout', 640), 'swords': cut('swords', 120)}
A['head_blink'] = cut('head_blink', 600 * 856 // 1032)  # same face scale as head_n (sheet heights differ)

def red_glow(im, r=26):
    a = np.asarray(im)[..., 3].astype(np.float32)
    g = Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))
    out = Image.new('RGBA', im.size, RED + (0,)); out.putalpha(g.point(lambda v: int(v * 0.75)))
    return out
GLOW = {k: red_glow(A[k]) for k in ('slash', 'three', 'front')}

def eyes_mask(im):
    """bright red pixels (the eyes + mask slits) -> pulsing glow layer"""
    a = np.asarray(im).astype(np.int16)
    m = ((a[..., 0] > 190) & (a[..., 1] < 70) & (a[..., 2] < 70) & (a[..., 3] > 200)).astype(np.uint8) * 255
    g = Image.fromarray(m).filter(ImageFilter.GaussianBlur(9))
    out = Image.new('RGBA', im.size, (255, 60, 50, 0)); out.putalpha(g); return out
EYES = eyes_mask(A['front'])

# ---------------- background: ink fog + rain + vignette
rng = np.random.default_rng(7)
def _fog():
    n = rng.random((60, 34)).astype(np.float32)
    im = Image.fromarray((n * 255).astype(np.uint8)).resize((1400, 2400), Image.BICUBIC).filter(ImageFilter.GaussianBlur(60))
    return np.asarray(im).astype(np.float32) / 255
FOG = _fog()
yy, xx = np.mgrid[0:H, 0:W]
VIG = (1 - 0.62 * (((xx - W / 2) / (W * 0.78)) ** 2 + ((yy - H * 0.47) / (H * 0.66)) ** 2)).clip(0.25, 1)[..., None].astype(np.float32)
GRAD = np.stack([np.full((H, W), NIGHT[i], np.float32) + np.linspace(6, -4, H)[:, None] for i in range(3)], -1)
DROPS = rng.random((140, 3))

def background(t, redness=0.0):
    ox, oy = int(80 + 60 * math.sin(t * 0.21)), int(200 + t * 22) % 400
    f = FOG[oy:oy + H, ox:ox + W][..., None]
    base = GRAD + f * np.array([46, 10, 12], np.float32) * (0.7 + 0.8 * redness) + f * 10
    base[..., 0] += 60 * redness * f[..., 0]
    img = Image.fromarray((base * VIG).clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img, 'RGBA')
    for x, y0, s in DROPS:                              # slanted rain
        y = (y0 * H + t * (1500 + 900 * s)) % (H + 200) - 100; X = x * W - (y - H / 2) * 0.12
        d.line([(X, y), (X - 9 - 8 * s, y + 46 + 40 * s)], fill=(200, 205, 215, int(28 + 40 * s)), width=2)
    return img

def paste(img, im, cx, by, alpha=1.0):
    """bottom-centre anchored paste with alpha"""
    if alpha <= 0: return
    if alpha < 1: im = im.copy(); im.putalpha(im.getchannel('A').point(lambda v: int(v * alpha)))
    img.alpha_composite(im, (int(cx - im.width / 2), int(by - im.height)))

def text_c(d, x, y, s, font, fill, anchor='mm', track=0):
    if not track: d.text((x, y), s, font=font, fill=fill, anchor=anchor); return
    ws = [d.textlength(ch, font=font) + track for ch in s]; x0 = x - (sum(ws) - track) / 2
    for ch, w_ in zip(s, ws): d.text((x0, y), ch, font=font, fill=fill, anchor='lm'); x0 += w_

def glow_text(img, xy, s, font, col, r=18, k=1.0, anchor='mm'):
    L = Image.new('RGBA', img.size, (0, 0, 0, 0)); ImageDraw.Draw(L).text(xy, s, font=font, fill=col + (255,), anchor=anchor)
    g = L.filter(ImageFilter.GaussianBlur(r)); g.putalpha(g.getchannel('A').point(lambda v: int(min(255, v * 1.6 * k))))
    img.alpha_composite(g); img.alpha_composite(L)

# ---------------- captions (karaoke, word by word)
def captions(img, t):
    for key, at in AT.items():
        words = VO[key]['text'].replace('...', '').split(); d0 = VO[key]['dur']
        if not (at - 0.05 <= t <= at + d0 + 0.25): continue
        wl = [len(w) + 2 for w in words]; tot = sum(wl); acc, i_now = 0, 0
        for i, w in enumerate(wl):
            if (t - at) / d0 * tot >= acc: i_now = i
            acc += w
        lo = max(0, i_now - (i_now % 4)); chunk = words[lo:lo + 4]
        d = ImageDraw.Draw(img, 'RGBA'); f = F('Black', 58); y = 1585
        tw = sum(d.textlength(w.upper() + ' ', font=f) for w in chunk)
        d.rounded_rectangle([W / 2 - tw / 2 - 26, y - 50, W / 2 + tw / 2 + 14, y + 48], 22, fill=(8, 8, 10, 170))
        x = W / 2 - tw / 2
        for j, w in enumerate(chunk):
            on = lo + j == i_now
            d.text((x, y), w.upper(), font=f, fill=RED if on else BONE, anchor='lm')
            x += d.textlength(w.upper() + ' ', font=f)
        return

# ---------------- ink wipe between scenes (diagonal brush stroke)
def ink_wipe(img, t, t0):
    k = seg(t, t0 - 0.35, t0 + 0.12)
    if k <= 0 or k >= 1: return
    L = Image.new('L', (W, H), 0); d = ImageDraw.Draw(L)
    c = lerp(-900, W + H + 300, eio(k)); wdt = 900
    d.polygon([(c - wdt, 0), (c, 0), (c - H * 0.55, H), (c - wdt - H * 0.55, H)], fill=255)
    for i in range(16):                                  # bristle edge
        o = (i * 97) % 220; d.line([(c + o * 0.3, i * H / 16), (c + o * 0.3 - H * 0.04, (i + 1) * H / 16)], fill=255, width=30)
    L = L.filter(ImageFilter.GaussianBlur(3)); img.paste(Image.new('RGBA', (W, H), REDD + (255,)), (0, 0), L)
    edge = L.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(6))
    img.paste(Image.new('RGBA', (W, H), RED + (255,)), (0, 0), edge.point(lambda v: min(255, v * 3)))

# ---------------- scene A: katana split-reveal
def scene_a(img, t):
    d = ImageDraw.Draw(img, 'RGBA')
    kin = eo(seg(t, 0.35, 1.15))
    paste(img, GLOW['slash'], lerp(W + 500, 690, kin), 1930, 0.35 + 0.65 * seg(t, SLASH, SLASH + 0.2))
    paste(img, A['slash'], lerp(W + 500, 690, kin) + (14 * math.sin(t * 40) * seg(t, SLASH, SLASH + 0.25) * (1 - seg(t, SLASH + 0.25, SLASH + 0.6))), 1930,
          0.8 - 0.4 * seg(t, SLASH + 0.6, 3.2))
    # headline layer, then split it along the cut line after the slash
    L = Image.new('RGBA', (W, H), (0, 0, 0, 0)); dl = ImageDraw.Draw(L)
    a_in = seg(t, 0.15, 0.6)
    text_c(dl, W / 2, 620, 'YOUR FIRST', F('Black', 132), BONE + (int(255 * a_in),))
    text_c(dl, W / 2, 790, 'AD', F('Black', 210), BONE + (int(255 * a_in),))
    sp = eo(seg(t, SLASH, SLASH + 0.45)) * 300
    # reveal FREE underneath
    if t >= SLASH:
        fr = back(seg(t, SLASH + 0.05, SLASH + 0.45))
        sz = int(lerp(380, 300, fr))
        glow_text(img, (W / 2, 740), 'FREE', F('Black', sz), RED, r=28, k=seg(t, SLASH, SLASH + 0.3))
        sub = seg(t, END['hook'] - 0.35, END['hook'] + 0.15)
        text_c(ImageDraw.Draw(img, 'RGBA'), W / 2, 960, 'IS ON US', F('Bold', 74), BONE + (int(255 * sub),), track=int(14 * (1 - sub) + 10))
    if sp <= 0:
        img.alpha_composite(L)
    else:
        m = Image.new('L', (W, H), 0); ImageDraw.Draw(m).polygon([(0, 0), (W, 0), (W, 520), (0, 900)], fill=255)
        up = Image.new('RGBA', (W, H), (0, 0, 0, 0)); up.paste(L, (0, 0), m)
        dn = Image.new('RGBA', (W, H), (0, 0, 0, 0)); dn.paste(L, (0, 0), Image.eval(m, lambda v: 255 - v))
        fade = 1 - seg(t, SLASH + 0.1, SLASH + 0.45)
        for part, dx, dy in ((up, -sp * 0.9, -sp * 1.4), (dn, sp * 0.9, sp * 1.4)):
            if fade > 0:
                part.putalpha(part.getchannel('A').point(lambda v: int(v * fade)))
                img.alpha_composite(part, (int(dx), int(dy)))
    # the cut: bright blade line sweeping top-right -> bottom-left
    k = seg(t, SLASH - 0.12, SLASH + 0.05)
    if 0 < k and t < SLASH + 0.5:
        p0, p1 = (W + 60, 500), (-60, 920)
        pe = (lerp(p0[0], p1[0], eo(k)), lerp(p0[1], p1[1], eo(k)))
        fade = 1 - seg(t, SLASH + 0.1, SLASH + 0.5)
        G = Image.new('RGBA', (W, H), (0, 0, 0, 0)); g = ImageDraw.Draw(G)
        g.line([p0, pe], fill=RED + (int(255 * fade),), width=34)
        G = G.filter(ImageFilter.GaussianBlur(14)); img.alpha_composite(G)
        ImageDraw.Draw(img).line([p0, pe], fill=(255, 240, 230), width=int(7 * fade) + 1)
    if SLASH <= t < SLASH + 0.12:                       # flash
        img.alpha_composite(Image.new('RGBA', (W, H), (255, 235, 225, int(150 * (1 - seg(t, SLASH, SLASH + 0.12))))))

# ---------------- scene B: three things, hanko stamps
STEP_T = [AT['steps'] + 1.55, AT['steps'] + 2.25, AT['steps'] + 2.95]
CARDS = [('YOUR LINK', 'shop or product page'), ('YOUR LOGO', 'or just your brand name'), ('YOUR GOAL', 'buy · follow · book')]
def scene_b(img, t):
    d = ImageDraw.Draw(img, 'RGBA')
    h = eo(seg(t, T_B, T_B + 0.4))
    text_c(d, 690, 330, 'SEND ME', F('Bold', 54), MUTED + (int(255 * h),), track=12)
    text_c(d, 690, 420, '3 THINGS', F('Black', 112), BONE + (int(255 * h),))
    for i, ((ttl, sub), ts) in enumerate(zip(CARDS, STEP_T)):
        k = seg(t, ts - 0.45, ts)
        if k <= 0: continue
        y = lerp(-300, 720 + i * 245, back(k, 1.2)); rot = (1 - eo(k)) * (-9 + 9 * i)
        C = Image.new('RGBA', (880, 210), (0, 0, 0, 0)); c = ImageDraw.Draw(C)
        c.rounded_rectangle([0, 0, 879, 209], 26, fill=BONE + (255,))
        c.text((210, 82), ttl, font=F('Black', 66), fill=INK, anchor='lm')
        c.text((212, 148), sub, font=F('Regular', 36), fill=(90, 86, 80), anchor='lm')
        st = seg(t, ts, ts + 0.22)                       # hanko stamp lands after the card
        if st > 0:
            s = lerp(1.7, 1.0, back(st, 2.2)); r = int(70 * s)
            c.ellipse([105 - r, 105 - r, 105 + r, 105 + r], outline=RED + (int(255 * min(1, st * 2)),), width=int(9 * s))
            c.text((105, 108), str(i + 1), font=F('Black', int(80 * s)), fill=RED + (int(255 * min(1, st * 2)),), anchor='mm')
        C = C.rotate(rot, resample=Image.BICUBIC, expand=True)
        img.alpha_composite(C, (int(W / 2 - C.width / 2), int(y - C.height / 2)))
    blink = any(abs(t - b) < 0.07 for b in (T_B + 0.9, T_B + 2.8))
    hd = A['head_blink'] if blink else A['head_n']
    bob = 8 * math.sin(t * 2.4); hin = eo(seg(t, T_B + 0.1, T_B + 0.6))
    hs = hd.resize((hd.width * 2 // 3, hd.height * 2 // 3))
    paste(img, hs, lerp(-200, 190, hin), 560 + bob)

# ---------------- scene C: the phone builds the ad live
PH = (560, 1080); PX, PY = 470, 330
def scene_c(img, t):
    b0, bd = AT['build'], VO['build']['dur']
    m_t, v_t, c_t, g_t = b0 + 0.25 * bd, b0 + 0.38 * bd, b0 + 0.5 * bd, b0 + 0.72 * bd
    kin = eo(seg(t, T_C, T_C + 0.6))
    paste(img, GLOW['three'], lerp(-420, 250, kin), 1960, 0.6)
    paste(img, A['three'], lerp(-420, 250, kin), 1960)
    d = ImageDraw.Draw(img, 'RGBA')
    text_c(d, W / 2, 255, 'BUILT FOR  TIKTOK · REELS · SHORTS', F('Bold', 38), BONE + (int(230 * kin),), track=3)
    pin = back(seg(t, T_C + 0.2, T_C + 0.8), 1.1); px = lerp(W + 40, PX, pin)
    P = Image.new('RGBA', (PH[0] + 40, PH[1] + 40), (0, 0, 0, 0)); p = ImageDraw.Draw(P, 'RGBA')
    p.rounded_rectangle([0, 0, PH[0] + 39, PH[1] + 39], 70, fill=(22, 22, 26, 255), outline=RED + (255,), width=4)
    p.rounded_rectangle([20, 20, PH[0] + 19, PH[1] + 19], 54, fill=(30, 26, 28, 255))
    p.rounded_rectangle([PH[0] / 2 - 60, 34, PH[0] / 2 + 100, 58], 12, fill=(10, 10, 12, 255))
    # product card with zoom ("motion")
    pc = eo(seg(t, T_C + 0.6, T_C + 1.1)); z = 1 + 0.06 * eio(seg(t, m_t, m_t + 1.6))
    cw, ch = 440 * z, 470 * z; cx, cy = 20 + PH[0] / 2, lerp(900, 360, pc)
    if pc > 0:
        p.rounded_rectangle([cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2], 34, fill=(58, 30, 32, int(255 * pc)))
        sh = (t * 0.7) % 1.4 - 0.2
        p.polygon([(cx - cw / 2 + cw * sh, cy - ch / 2), (cx - cw / 2 + cw * sh + 70, cy - ch / 2), (cx - cw / 2 + cw * sh - 50, cy + ch / 2), (cx - cw / 2 + cw * sh - 120, cy + ch / 2)],
                  fill=(255, 255, 255, int(28 * pc)))
        p.text((cx, cy - 30), 'YOUR', font=F('Black', 70), fill=BONE + (int(255 * pc),), anchor='mm')
        p.text((cx, cy + 50), 'PRODUCT', font=F('Black', 70), fill=RED + (int(255 * pc),), anchor='mm')
    if m_t <= t < m_t + 1.0:                               # motion: spinning ring
        a = (t - m_t) * 540; p.arc([cx - 70, cy + 150, cx + 70, cy + 290], a, a + 250, fill=BONE + (220,), width=8)
    vo_k = seg(t, v_t, v_t + 0.4)                          # voice: live waveform
    if vo_k > 0:
        for i in range(22):
            hgt = (18 + 46 * abs(math.sin(t * 9 + i * 0.7) * math.sin(t * 3.1 + i))) * vo_k
            x = 80 + i * 20; p.rounded_rectangle([x, 660 - hgt, x + 10, 660 + hgt], 5, fill=RED + (230,))
    words = ['WAIT', 'FOR', 'IT', '...', 'FREE']               # captions pop word by word
    for i, w in enumerate(words):
        k = seg(t, c_t + i * 0.22, c_t + i * 0.22 + 0.18)
        if k <= 0: continue
        s = lerp(1.5, 1, back(k)); f = F('Black', int(50 * s))
        p.text((60 + sum(p.textlength(x + ' ', font=F('Black', 50)) for x in words[:i]), 815), w, font=f,
               fill=(RED if w == 'FREE' else BONE) + (255,), anchor='lm')
    img.alpha_composite(P, (int(px - 20), PY - 20))
    tags = ['#shorts', '#fyp', '#anime', '#takekash']           # tags fly in on curves and dock
    for i, tg in enumerate(tags):
        k = seg(t, g_t + i * 0.28, g_t + i * 0.28 + 0.55)
        if k <= 0: continue
        e = eo(k); tx, ty = px + 50 + (i % 2) * 240, PY + 890 + (i // 2) * 84
        sx, sy = (-120 if i % 2 == 0 else W + 120), 1250 + i * 60
        x = lerp(sx, tx, e) + math.sin(e * math.pi) * (-160 if i % 2 else 160); y = lerp(sy, ty, e) - math.sin(e * math.pi) * 240
        f = F('Bold', 40); tw = d.textlength(tg, font=f)
        d.rounded_rectangle([x, y - 32, x + tw + 36, y + 32], 30, fill=RED + (235,))
        d.text((x + 18, y), tg, font=f, fill=BONE, anchor='lm')

# ---------------- scene D: NO CARD stamp + 48H counter
def scene_d(img, t, shake):
    d = ImageDraw.Draw(img, 'RGBA'); s0 = AT['deliver']
    st = seg(t, s0 - 0.05, s0 + 0.18)
    if st > 0:
        sc = lerp(2.4, 1.0, eo(st)); S = Image.new('RGBA', (900, 300), (0, 0, 0, 0)); s = ImageDraw.Draw(S)
        s.rounded_rectangle([10, 10, 889, 289], 26, outline=RED + (255,), width=16)
        s.text((450, 150), 'NO CARD', font=F('Black', 150), fill=RED + (255,), anchor='mm')
        S = S.resize((int(900 * sc), int(300 * sc))).rotate(-7, resample=Image.BICUBIC, expand=True)
        S.putalpha(S.getchannel('A').point(lambda v: int(v * min(1, st * 1.5))))
        img.alpha_composite(S, (int(W / 2 - S.width / 2 + shake[0]), int(470 - S.height / 2 + shake[1])))
    nk = seg(t, s0 + 0.75, s0 + 1.45)
    if nk > 0:
        n = int(round(48 * eo(nk)))
        glow_text(img, (330, 930), f'{n:02d}', F('Black', 330), BONE, r=10, k=0.4)
        d.text((610, 990), 'H', font=F('Black', 170), fill=RED, anchor='mm')
        d.text((90, 1160), 'YOUR AD,', font=F('Bold', 56), fill=MUTED, anchor='lm')
        d.text((90, 1235), 'DELIVERED.', font=F('Black', 64), fill=BONE, anchor='lm')
    hk = back(seg(t, s0 + 0.1, s0 + 0.5))
    paste(img, A['head_shout'], lerp(W + 400, W - 150, hk), 1500 + 30 * (1 - hk))

# ---------------- scene E: enso CTA
def scene_e(img, t):
    c0 = AT['cta']; d = ImageDraw.Draw(img, 'RGBA')
    ek = eio(seg(t, T_E, T_E + 1.3))
    if ek > 0:                                              # enso brush circle draws behind KASH
        E = Image.new('RGBA', (W, H), (0, 0, 0, 0)); e = ImageDraw.Draw(E)
        for w_, a_ in ((70, 120), (44, 230)):
            e.arc([90, 520, 990, 1420], 110, 110 + 330 * ek, fill=RED + (a_,), width=w_)
        img.alpha_composite(E.filter(ImageFilter.GaussianBlur(1.5)))
    kin = eo(seg(t, T_E, T_E + 0.7))
    paste(img, GLOW['front'], W / 2, lerp(2450, 2130, kin), 0.8)
    paste(img, A['front'], W / 2, lerp(2450, 2130, kin))
    pulse = 0.55 + 0.45 * math.sin(t * 5.5) ** 2
    paste(img, EYES, W / 2, lerp(2450, 2130, kin), pulse * kin)
    hk = eo(seg(t, c0 - 0.2, c0 + 0.3))
    glow_text(img, (W / 2, 250), 'FREE AD', F('Black', 150), BONE, r=14, k=0.5 * hk)
    bk = back(seg(t, c0 + 0.15, c0 + 0.55)); bp = 1 + 0.04 * math.sin(t * 6)
    if bk > 0:
        bw, bh = 640 * bk * bp, 120 * bk * bp
        d.rounded_rectangle([W / 2 - bw / 2, 390 - bh / 2, W / 2 + bw / 2, 390 + bh / 2], 60, fill=RED)
        if bk > 0.6:
            d.text((W / 2 - 24, 392), 'LINK IN BIO', font=F('Black', int(58 * bp)), fill=BONE, anchor='mm')
            ax = W / 2 + 205 + 8 * math.sin(t * 8); d.polygon([(ax, 372), (ax + 30, 392), (ax, 412)], fill=BONE)
    ik = seg(t, END['cta'] - 0.4, END['cta'] + 0.4)          # like / comment / share row
    if ik > 0:
        labels = ['LIKE', 'COMMENT', 'SHARE']
        for i, lb in enumerate(labels):
            k = back(seg(t, END['cta'] - 0.4 + i * 0.15, END['cta'] + i * 0.15))
            x = W / 2 + (i - 1) * 300; y = 1700
            d.rounded_rectangle([x - 130, y - 50, x + 130, y + 50], 50, fill=(10, 10, 12, int(220 * cl(k))), outline=RED, width=3)
            if k > 0.08: d.text((x, y), lb, font=F('Black', max(8, int(44 * cl(k)))), fill=BONE, anchor='mm')
    text_c(d, W / 2, 1820, 'TAKEKASH', F('Black', 40), BONE + (int(200 * kin),), track=18)

# ---------------- frame
def frame(t):
    s0 = AT['deliver']
    shk = 0.0
    for t0, amp in ((SLASH, 22), (s0, 30)) + tuple((ts, 6) for ts in STEP_T):
        if t0 <= t < t0 + 0.3: shk = max(shk, amp * (1 - (t - t0) / 0.3))
    sh = (shk * math.sin(t * 97), shk * math.cos(t * 83))
    redness = 0.9 * seg(t, s0, s0 + 0.2) * (1 - seg(t, s0 + 0.6, T_E)) + 0.25 * seg(t, SLASH, SLASH + 0.3) * (1 - seg(t, SLASH + 0.3, T_B))
    img = background(t, redness).convert('RGBA')
    if t < T_B: scene_a(img, t)
    elif t < T_C: scene_b(img, t)
    elif t < T_D: scene_c(img, t)
    elif t < T_E: scene_d(img, t, sh)
    else: scene_e(img, t)
    captions(img, t)
    for t0 in (T_B, T_C, T_D, T_E): ink_wipe(img, t, t0)
    out = img.convert('RGB')
    if shk: out = out.transform(out.size, Image.AFFINE, (1, 0, -sh[0], 0, 1, -sh[1]), Image.BILINEAR)
    fin = seg(t, DUR - 0.5, DUR)
    if fin: out = Image.blend(out, Image.new('RGB', out.size, (0, 0, 0)), fin)
    return out

if __name__ == '__main__':
    if '--stills' in sys.argv:
        for x in sys.argv[sys.argv.index('--stills') + 1:]:
            frame(float(x)).save(os.path.join(OUT, f'still_{float(x):05.2f}.jpg'), quality=88)
        sys.exit()
    n = int(DUR * FPS); lo = int(sys.argv[3]) if len(sys.argv) > 3 else 0; hi = int(sys.argv[4]) if len(sys.argv) > 4 else n
    tmp = os.path.join(OUT, f'part_{lo:05d}.tmp.mp4')
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-tune', 'grain', '-maxrate', '16M', '-bufsize', '32M', '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    for i in range(lo, hi): p.stdin.write(frame(i / FPS).tobytes())
    p.stdin.close(); p.wait()
    if p.returncode == 0: os.replace(tmp, os.path.join(OUT, f'part_{lo:05d}.mp4'))
    print('DUR', DUR, 'frames', lo, hi)
