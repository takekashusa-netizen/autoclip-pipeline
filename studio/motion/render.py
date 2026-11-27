"""KASH motion-comic renderer: the real character art (4x-upscaled sheet assets + poster) animated
over the stage, with the narrated tour from the King voice. Usage: python render_kash.py preview [t..] | render LO HI NAME"""
import math, os, random, subprocess, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import config
import scenekit as S
import tour as T
from scenekit import W, H, FPS, RED, BONE, MUTED, F, cl, seg, eo, eio, lerp, glow, brush_text, blade_text, forge_text

K = config.WORK
def load(name): return Image.open(f'{config.ASSETS}/{name}.png').convert('RGBA')
A = {k: load(k) for k in ('front', 'three', 'back', 'crouch', 'slash', 'head_n', 'head_q', 'head_blink', 'head_shout')}
POSTER = Image.open(f'{K}/poster2x.png').convert('RGB')
STAGE = Image.open(f'{K}/stage.png').convert('RGB')
STAGE = ImageEnhance.Brightness(STAGE).enhance(0.55)

# ---------------- per-asset masks: scarf (for flutter) + emissive eyes (for glow)
def masks(img, eye_band):
    a = np.asarray(img).astype(np.int16)
    r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    red = ((r > 110) & (r > g * 1.9) & (r > b * 1.7) & (al > 100)).astype(np.float32)
    red = cv2.GaussianBlur(red, (0, 0), 9)
    eye = ((r > 200) & (g < 95) & (b < 95) & (al > 200)).astype(np.uint8)
    hgt = eye.shape[0]; band = np.zeros_like(eye); band[int(hgt * eye_band[0]):int(hgt * eye_band[1])] = 1
    eye = eye * band
    return red, eye
BANDS = {'front': (0.04, 0.12), 'three': (0.04, 0.12), 'back': (0, 0), 'crouch': (0.05, 0.2), 'slash': (0, 0),
         'head_n': (0.33, 0.50), 'head_q': (0.30, 0.48), 'head_blink': (0, 0), 'head_shout': (0.30, 0.48)}
M = {k: masks(v, BANDS[k]) for k, v in A.items()}

def char_layer(name, height, t, sway=1.0, flutter=1.0, breathe=1.0, flip=False):
    """returns RGBA of the asset at display height with idle motion + scarf flutter, and an eye-glow layer"""
    img = A[name]; red, eye = M[name]
    s = height / img.height
    w_, h_ = max(2, int(img.width * s)), max(2, int(height * (1 + 0.006 * breathe * math.sin(t * 2.1))))
    arr = np.asarray(img.resize((w_, h_), Image.LANCZOS))
    rm = cv2.resize(red, (w_, h_))
    if flutter > 0:
        yy, xx = np.mgrid[0:h_, 0:w_].astype(np.float32)
        amp = 7 * flutter * (h_ / 1500)
        dx = amp * np.sin(yy * 0.018 - t * 5.0 + xx * 0.006) * rm
        dy = amp * 0.6 * np.cos(xx * 0.02 - t * 4.2) * rm
        arr = cv2.remap(arr, xx + dx, yy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    out = Image.fromarray(arr)
    em = None
    if eye.any():
        e = cv2.resize(eye * 255, (w_, h_), interpolation=cv2.INTER_NEAREST)
        e = cv2.dilate(e, np.ones((3, 3), np.uint8))
        lay = np.zeros((h_, w_, 4), np.uint8); lay[..., 0] = 255; lay[..., 1] = 60; lay[..., 2] = 40; lay[..., 3] = e
        em = Image.fromarray(lay)
    if flip:
        out = out.transpose(Image.FLIP_LEFT_RIGHT); em = em.transpose(Image.FLIP_LEFT_RIGHT) if em else None
    rot = sway * 0.5 * math.sin(t * 0.9)
    if abs(rot) > 0.01:
        out = out.rotate(rot, resample=Image.BICUBIC, expand=False, center=(w_ / 2, h_))
        if em: em = em.rotate(rot, resample=Image.BICUBIC, expand=False, center=(w_ / 2, h_))
    return out, em

def place(img, name, cx, base_y, height, t, eye_on=1.0, rim=True, **kw):
    ch, em = char_layer(name, height, t, **kw)
    x, y = int(cx - ch.width / 2), int(base_y - ch.height)
    if rim:   # red rim light hugging the silhouette so he separates from the night
        a = ch.getchannel('A'); sm = a.resize((max(1, a.width // 4), max(1, a.height // 4)))
        rg = sm.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(4)).resize(a.size)
        rl = Image.new('RGBA', a.size, RED + (0,)); rl.putalpha(rg.point(lambda v: int(v * 0.55)))
        img.alpha_composite(rl, (x, y))
    # contact shadow
    sh = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).ellipse([cx - ch.width * 0.42, base_y - 30, cx + ch.width * 0.42, base_y + 26], fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
    img.alpha_composite(ch, (x, y))
    if em is not None and eye_on > 0:
        e2 = Image.new('RGBA', (W, H), (0, 0, 0, 0)); e2.alpha_composite(em, (x, y))
        e2.putalpha(e2.getchannel('A').point(lambda v: int(v * eye_on)))
        img.alpha_composite(glow(e2, 10, 2.4))
    return (x, y, ch.width, ch.height)

def stage(t, pan=0.0, zoom=1.0, dark=1.0):
    sw = int(W * 1.18 * zoom); sh_ = int(sw * STAGE.height / STAGE.width)
    st = STAGE.resize((sw, sh_), Image.BILINEAR)
    x0 = int((sw - W) / 2 + pan * (sw - W) / 2 + math.sin(t * 0.3) * 8); y0 = int((sh_ - H) / 2)
    bg = st.crop((x0, y0, x0 + W, y0 + H)).convert('RGBA')
    fog = Image.new('RGBA', (W, H), (0, 0, 0, 0)); fd = ImageDraw.Draw(fog)
    for i in range(0, H, 8):
        k = i / H; fd.rectangle([0, i, W, i + 8], fill=(10, 8, 10, int(120 * (1 - k) ** 2 + 60 * k ** 3)))
    bg.alpha_composite(fog)
    if dark < 1: bg.alpha_composite(Image.new('RGBA', (W, H), (0, 0, 0, int(255 * (1 - dark)))))
    return bg

def poster(t, zoom=1.0, cy=0.5, bright=1.0):
    sc = H / POSTER.height * zoom; pw, ph = int(POSTER.width * sc), int(POSTER.height * sc)
    p = POSTER.resize((pw, ph), Image.BILINEAR)
    x0 = (pw - W) // 2; y0 = int((ph - H) * cy)
    img = p.crop((x0, y0, x0 + W, y0 + H)).convert('RGBA')
    if bright < 1: img.alpha_composite(Image.new('RGBA', (W, H), (0, 0, 0, int(255 * (1 - bright)))))
    return img, sc, x0, y0

# ---------------- holo panel, flat 2D with a perspective lean
def panel2d(img, key, cx, cy, width, lean, t, a, b):
    u = seg(t, a, a + 0.6); out = seg(t, b - 0.4, b)
    if u <= 0 or out >= 1: return
    card = T.PANELS[key].copy(); PW_, PH_ = card.size
    reveal = eo(u)
    m = Image.new('L', card.size, 0); ImageDraw.Draw(m).rectangle([0, 0, PW_, PH_ * reveal], fill=255)
    from PIL import ImageChops
    al = ImageChops.multiply(card.getchannel('A'), m).point(lambda v: int(v * (0.92 + 0.08 * math.sin(t * 9)) * (1 - out)))
    card.putalpha(al)
    cd = ImageDraw.Draw(card)
    for yy in range(0, PH_, 6): cd.line([(0, yy), (PW_, yy)], fill=(0, 0, 0, 40))
    if reveal < 1: cd.rectangle([0, PH_ * reveal - 4, PW_, PH_ * reveal + 4], fill=(255, 120, 90, 230))
    wd = width * (0.8 + 0.2 * eo(u)); hd = wd * PH_ / PW_
    near, far = (1.0, 0.86) if lean > 0 else (0.86, 1.0)
    cy += math.sin(t * 1.3) * 6
    pts = [(cx - wd / 2, cy - hd / 2 * near), (cx + wd / 2, cy - hd / 2 * far), (cx + wd / 2, cy + hd / 2 * far), (cx - wd / 2, cy + hd / 2 * near)]
    warped = card.transform((W, H), Image.PERSPECTIVE, T._coeffs(pts, [(0, 0), (PW_, 0), (PW_, PH_), (0, PH_)]), Image.BICUBIC)
    edge = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(edge).polygon(pts, outline=RED + (int(220 * (1 - out)),))
    img.alpha_composite(glow(edge, 16, 1.6)); img.alpha_composite(warped)

# ---------------- talking energy from the narration (drives head bob in bust shots)
import soundfile as sf
ENV = {}
for k_, at in T.VO_AT.items():
    a_, sr = sf.read(f'{T.TTS}/vo_{k_}.wav', dtype='float32')
    hop = sr // FPS; n = len(a_) // hop
    e = np.sqrt((a_[:n * hop].reshape(n, hop) ** 2).mean(1)); ENV[k_] = (at, e / (e.max() + 1e-6))
def energy(t):
    for k_, (at, e) in ENV.items():
        i = int((t - at) * FPS)
        if 0 <= i < len(e): return float(e[i])
    return 0.0

# ---------------- shot list (times come from the narration timeline)
ST = {k: (a, b) for k, a, b, p in T.STOPS}
SL = T.SLASH
def frame(t, fi):
    flashes = [(0.55, 0.12), (0.75, 0.08), (1.5, 0.1), (2.8, 0.25)]
    fl = max([1 - (t - a) / d_ for a, d_ in flashes if 0 <= t - a < d_] + [0])
    cut_flash = 0.0
    if t < 3.4:                                                    # A: poster reveal in the storm
        bright = 0.18 + 0.82 * fl + 0.55 * eo(seg(t, 2.8, 3.4))
        img, sc, x0, y0 = poster(t, 1.0 + 0.05 * t / 3.4, 0.5, min(1, bright))
        S.bolt(img, t, 3, W * 0.78, (1 - (t - 2.8) / 0.25) if 2.8 <= t < 3.05 else 0)
        S.bolt(img, t, 9, W * 0.15, (1 - (t - 0.55) / 0.12) if 0.55 <= t < 0.67 else 0)
    elif t < ST['clips'][0]:                                       # B: the King speaks (bust)
        u = seg(t, 3.4, ST['clips'][0]); e = energy(t)
        img = stage(t, -0.1, 1.05 + 0.04 * u)
        name = 'head_blink' if any(0 <= t - b < 0.12 for b in (4.7, 6.3)) else 'head_n'
        place(img, name, W / 2, 1330 + e * 6, 1060 * (1 + 0.05 * u), t, sway=0.6, flutter=0.6, breathe=1.5)
        blade_text(img, [('WELCOME TO', BONE), ('TAKEKASH.', RED)], t, 3.7, 400, 104, 112, None)
        cut_flash = 0.5 * (1 - seg(t, 3.4, 3.55))
    elif t < SL - 1.0:                                             # C: clip studio — 3/4 full body + panel
        a, b = ST['clips']; u = seg(t, a, SL - 1.0)
        img = stage(t, 0.35, 1.0 + 0.04 * u)
        place(img, 'three', 770, 1860, 1620 * (1 + 0.03 * u), t)
        panel2d(img, 'clips', 330, 930, 560, 1, t, a, b)
        cut_flash = 0.4 * (1 - seg(t, a, a + 0.15))
    elif t < SL:                                                   # D1: the draw — crouch pose
        u = seg(t, SL - 1.0, SL)
        img = stage(t, 0.0, 1.08 + 0.06 * u)
        place(img, 'crouch', W / 2 + 20, 1720, 1250 * (1 + 0.12 * eo(u)), t, sway=0.2, flutter=1.4)
        cut_flash = 0.5 * (1 - seg(t, SL - 1.0, SL - 0.88))
    elif t < ST['clips'][1]:                                       # D2: the cut — overhead slash pose
        u = seg(t, SL, ST['clips'][1])
        img = stage(t, -0.2, 1.12 - 0.05 * u)
        place(img, 'slash', 600, 1860, 1700, t, sway=0.2, flutter=1.6)
        S.hex_shock(img, S.Cam(0.0, 3.5, 0.9, 1.0, 1.55), t, SL + 0.05)
    elif t < ST['seo'][1]:                                         # E: SEO — front, left; panel right
        a, b = ST['seo']; u = seg(t, a, b)
        img = stage(t, -0.35, 1.0 + 0.04 * u)
        place(img, 'front', 300, 1850, 1600 * (1 + 0.03 * u), t)
        panel2d(img, 'seo', 760, 900, 560, -1, t, a, b)
        cut_flash = 0.4 * (1 - seg(t, a, a + 0.15))
    elif t < ST['overlay'][1]:                                     # F: Overlays — back view, he studies the screen
        a, b = ST['overlay']; u = seg(t, a, b)
        img = stage(t, 0.3, 1.04 - 0.03 * u)
        panel2d(img, 'overlay', 330, 820, 580, 1, t, a, b)
        place(img, 'back', 850, 1920, 1560, t, sway=0.4)
        cut_flash = 0.4 * (1 - seg(t, a, a + 0.15))
    elif t < ST['editflow'][1]:                                    # G: EditFlow — 3/4 bust bottom-left; panel top-right
        a, b = ST['editflow']; u = seg(t, a, b); e = energy(t)
        img = stage(t, -0.25, 1.06 + 0.04 * u)
        panel2d(img, 'editflow', 700, 760, 600, -1, t, a, b)
        place(img, 'head_q', 360, 1560 + e * 5, 900, t, sway=0.5, flutter=0.6, breathe=1.4)
        cut_flash = 0.4 * (1 - seg(t, a, a + 0.15))
    elif t < T.LOCK0:                                              # H: the gate — towering low angle
        u = seg(t, T.GATE0, T.LOCK0)
        img = stage(t, 0.0, 1.1 + 0.06 * u)
        place(img, 'front', W / 2, 2080 + 60 * (1 - eo(u)), 2050 * (1 + 0.05 * u), t)
        S.hex_shock(img, S.Cam(0.0, 3.0, 0.4, 1.0, 1.55), t, T.GATE0 + 0.1)
        brush_text(img, 'ONLY 90+', t, T.GATE0 + 0.4, 520, 140, BONE)
        brush_text(img, 'LEAVES THE DOJO', t, T.GATE0 + 1.4, 680, 84, BONE, brush=False)
        cut_flash = 0.4 * (1 - seg(t, T.GATE0, T.GATE0 + 0.15))
    else:                                                          # I: poster + forged lockup
        u = seg(t, T.LOCK0, T.DUR)
        img, *_ = poster(t, 1.12 - 0.08 * u, 0.25, 0.42)
        forge_text(img, t, T.LOCK0 + 0.3, 600, 810, 230)
        uu = eo(seg(t, T.LOCK0 + 1.8, T.LOCK0 + 2.2))
        if uu > 0:
            d = ImageDraw.Draw(img); fn = F('Bold', 52); ww = fn.getlength('takekash.com') + 90
            d.rounded_rectangle([W / 2 - ww / 2, 920, W / 2 + ww / 2, 1016], 48, fill=RED + (int(255 * uu),))
            d.text((W / 2, 986), 'takekash.com', font=fn, fill=BONE + (int(255 * uu),), anchor='ms')
            d.text((W / 2, 1090), 'Clips · SEO · Overlays · EditFlow', font=F('Medium', 36), fill=MUTED + (int(255 * uu),), anchor='ms')
            d.text((W / 2, 1155), '@gtaxzombies', font=F('Bold', 44), fill=BONE + (int(255 * uu),), anchor='ms')
        cut_flash = 0.6 * (1 - seg(t, T.LOCK0, T.LOCK0 + 0.2))
    # slash streak across the frame
    if SL - 0.2 <= t < SL + 0.35:
        u = seg(t, SL - 0.2, SL + 0.02); fade_ = 1 - seg(t, SL, SL + 0.35)
        tl = Image.new('RGBA', (W, H), (0, 0, 0, 0)); td = ImageDraw.Draw(tl)
        P0, P1 = (W * 1.05, H * 0.18), (-W * 0.05, H * 0.78)
        td.line([P0, (lerp(P0[0], P1[0], u), lerp(P0[1], P1[1], u))], fill=(255, 235, 225, int(255 * fade_)), width=int(30 * fade_) + 2)
        img.alpha_composite(glow(tl, 22, 1.6))
    S.rain(img, t, 1.0, fl)
    T.route(img, t)
    T.subtitles(img, t)
    split = None
    if SL <= t < SL + 0.8:
        k = seg(t, SL, SL + 0.15); back_ = seg(t, SL + 0.4, SL + 0.8)
        split = (70 * eo(k) * (1 - eio(back_)), 1.0 - back_)
    fl2 = max(cut_flash, 0.7 * (1 - seg(t, SL - 0.02, SL + 0.25)) if t >= SL - 0.02 else 0)
    return S.finish(img, fi, fade=seg(t, T.DUR - 0.5, T.DUR), flash=fl2 + (fl * 0.12 if t >= 3.4 else 0), split=split)

def render(lo, hi, name):
    od = config.OUT
    out, tmp = f'{od}/{name}.mp4', f'{od}/{name}.tmp.mp4'
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-tune', 'grain', '-maxrate', '18M', '-bufsize', '36M',
                          '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    for i in range(int(round(lo * FPS)), int(round(hi * FPS))):
        p.stdin.write(frame(i / FPS, i).tobytes())
    p.stdin.close()
    if p.wait() == 0: os.replace(tmp, out); print('ok', name)
    else: print('FAIL', name)

if __name__ == '__main__':
    if sys.argv[1] == 'preview':
        ts = [float(x) for x in sys.argv[2:]] or [2.9, 5.2, 9.5, SL - 0.4, SL + 0.3, 16.0, 21.5, 27.0, 33.0, 38.5]
        ims = [Image.fromarray(frame(x, 1)).resize((216, 384)) for x in ts]
        sh = Image.new('RGB', (216 * 5, 384 * 2))
        for i, im in enumerate(ims): sh.paste(im, ((i % 5) * 216, (i // 5) * 384))
        sh.save(f'{config.OUT}/preview.jpg', quality=88); print('done')
    else:
        render(float(sys.argv[2]), float(sys.argv[3]), sys.argv[4])
