"""Brand ad generator: fulfills a TakeKash free-ad request end to end.
    python3 brandad.py brief.json OUT_DIR            -> OUT_DIR/<slug>-ad-9x16.mp4 (+ voice, score, stills)
brief.json:
  {"brand": "Sunsentry", "headline": "Never charge your camera again", "benefits": ["...", "...", "..."],
   "goal": "buy" | "follow" | "book" | "download", "url": "sunsentry.com",
   "colors": {"primary": "#F5B700", "accent": "#FFFFFF", "bg": "#0B1220"},
   "logo": "path/to/logo.png" (optional), "product": "path/to/product.png" (optional, transparent PNG best),
   "voice": "female" | "male" | "king", "watermark": true}
Motion: logo slam + radial burst, word-by-word headline, floating product on a light ring, benefit pills with
check marks, pulsing goal button. Karaoke captions, ducked voice over a generated beat. All local, no paid APIs.
"""
import json, math, os, re, subprocess, sys
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__)); FD = os.path.join(HERE, 'fonts')
VOICES = {'female': dict(voices={'af_heart': 0.7, 'af_nova': 0.3}, semitones=0.0),
          'male': dict(voices={'am_michael': 0.7, 'am_eric': 0.3}, semitones=-0.5),
          'king': {}}
GOAL = {'buy': 'SHOP NOW', 'follow': 'FOLLOW NOW', 'book': 'BOOK NOW', 'download': 'GET THE APP'}
GOAL_VO = {'buy': 'Shop now', 'follow': 'Follow now', 'book': 'Book today', 'download': 'Download it today'}

_fc = {}
def F(w, s):
    s = max(6, int(s)); k = (w, s)
    if k not in _fc: _fc[k] = ImageFont.truetype(os.path.join(FD, f'Poppins-{w}.ttf'), s)
    return _fc[k]
def cl(x, a=0.0, b=1.0): return max(a, min(b, x))
def seg(t, a, b): return cl((t - a) / (b - a))
def eo(x): x = cl(x); return 1 - (1 - x) ** 3
def back(x, s=1.70158): x = cl(x); x -= 1; return x * x * ((s + 1) * x + s) + 1
def lerp(a, b, k): return a + (b - a) * k
def hexc(h): h = h.lstrip('#'); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def slug(s): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-') or 'brand'

# ---------------------------------------------------------------- setup (module globals, set by load())
B = {}; C = {}; VO = {}; AT = {}; DUR = 0.0; LOGO = None; PROD = None; BG = None

def lines_of(b):
    goal = b.get('goal', 'buy')
    return [('hook', b['headline']), ('b1', b['benefits'][0]), ('b2', b['benefits'][1]), ('b3', b['benefits'][2]),
            ('cta', f"{GOAL_VO.get(goal, 'Shop now')} at {b['url']}" if b.get('url') else GOAL_VO.get(goal, 'Shop now'))]

def load(brief_path, out):
    global B, C, VO, AT, DUR, LOGO, PROD, BG
    B = json.load(open(brief_path)); bd = os.path.dirname(os.path.abspath(brief_path))
    col = B.get('colors', {}); C = {'p': hexc(col.get('primary', '#E2262B')), 'a': hexc(col.get('accent', '#FFFFFF')), 'bg': hexc(col.get('bg', '#0E0E10'))}
    VO = json.load(open(os.path.join(out, 'vo', 'vo.json')))
    t = 0.6; AT = {}
    for k in ('hook', 'b1', 'b2', 'b3', 'cta'):
        AT[k] = round(t, 2); t += VO[k]['dur'] + (0.9 if k == 'hook' else 0.35)
    DUR = round(t + 1.6, 2)
    def img(key, h):
        p = B.get(key)
        if not p: return None
        p = p if os.path.isabs(p) else os.path.join(bd, p)
        im = Image.open(p).convert('RGBA'); s = h / max(im.height, im.width * 0.8)
        return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    LOGO = img('logo', 300); PROD = img('product', 760)
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.45) / H) ** 2)
    base = np.array(C['bg'], np.float32)[None, None] * (1.05 - 0.7 * r[..., None]).clip(0.3, 1.1)
    base += np.array(C['p'], np.float32)[None, None] * (0.22 * np.exp(-r * 4))[..., None]
    BG = base.clip(0, 255).astype(np.uint8)

def monogram(size):
    """no logo/product supplied: a clean brand card in the brand colours"""
    M = Image.new('RGBA', (size, size), (0, 0, 0, 0)); d = ImageDraw.Draw(M)
    d.rounded_rectangle([0, 0, size - 1, size - 1], size // 6, fill=C['p'] + (255,))
    name = B['brand']; f = F('Black', size * 0.9 / max(3, len(name)) * 1.6)
    d.text((size / 2, size / 2), name.upper()[:12], font=f, fill=C['bg'] + (255,), anchor='mm')
    return M

def contrast(c): return (12, 12, 14) if sum(c) > 400 else (250, 250, 248)

# ---------------------------------------------------------------- scenes
def comp(img, X, pos=(0, 0)):
    """alpha-blend X onto an RGB frame (Draw(img,'RGBA') only blends on RGB images)"""
    img.paste(X, (int(pos[0]), int(pos[1])), X)

def background(t):
    img = Image.fromarray(BG); d = ImageDraw.Draw(img, 'RGBA')
    for i in range(7):                                   # slow diagonal light bands
        x = ((t * 60 + i * 260) % (W + 900)) - 450
        d.polygon([(x, 0), (x + 90, 0), (x - 500, H), (x - 590, H)], fill=C['p'] + (10,))
    return img

def burst(img, t, t0, cx, cy):
    k = seg(t, t0, t0 + 0.7)
    if k <= 0 or k >= 1: return
    d = ImageDraw.Draw(img, 'RGBA'); r0, r1 = 120 + 500 * eo(k), 160 + 700 * eo(k)
    for i in range(18):
        a = i / 18 * 2 * math.pi + 0.2
        d.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
               fill=C['p'] + (int(220 * (1 - k)),), width=10)
    d.ellipse([cx - r0, cy - r0, cx + r0, cy + r0], outline=C['a'] + (int(160 * (1 - k)),), width=6)

def scene_hook(img, t):
    t0 = AT['hook'] - 0.45; k = back(seg(t, t0, t0 + 0.35), 2.0)
    logo = LOGO or monogram(300)
    if k > 0:
        s = lerp(2.2, 1.0, k); L = logo.resize((max(1, int(logo.width * s)), max(1, int(logo.height * s))))
        L.putalpha(L.getchannel('A').point(lambda v: int(v * cl(k * 2))))
        comp(img, L, (int(W / 2 - L.width / 2), int(560 - L.height / 2)))
    burst(img, t, t0 + 0.3, W / 2, 560)
    words = B['headline'].upper().split(); d = ImageDraw.Draw(img, 'RGBA')
    f = F('Black', 104 if len(B['headline']) < 26 else 86); rows, row = [], []
    for w in words:                                      # wrap to ~900px
        if row and d.textlength(' '.join(row + [w]), font=f) > 920: rows.append(row); row = []
        row.append(w)
    rows.append(row); n = 0; y0 = 900
    for ri, rw in enumerate(rows):
        x = W / 2 - d.textlength(' '.join(rw), font=f) / 2
        for w in rw:
            wk = back(seg(t, AT['hook'] + n * 0.16, AT['hook'] + n * 0.16 + 0.25))
            if wk > 0:
                yy = y0 + ri * 120 + 40 * (1 - wk)
                d.text((x, yy), w, font=f, fill=(C['p'] if n == len(words) - 1 else C['a']) + (int(255 * cl(wk)),), anchor='lm')
            x += d.textlength(w + ' ', font=f); n += 1

def scene_product(img, t):
    t0 = AT['b1'] - 0.5; k = eo(seg(t, t0, t0 + 0.6)); d = ImageDraw.Draw(img, 'RGBA')
    cx, cy = W / 2, 760 + 16 * math.sin(t * 2.2)
    rr = 330 * k                                         # light ring
    if rr > 2:
        G = Image.new('RGBA', (W, H), (0, 0, 0, 0)); g = ImageDraw.Draw(G)
        a = t * 70; g.arc([cx - rr, cy - rr * 0.35 + 300, cx + rr, cy + rr * 0.35 + 300], a, a + 280, fill=C['p'] + (230,), width=14)
        comp(img, G.filter(ImageFilter.GaussianBlur(6))); comp(img, G)
    P = PROD or (LOGO and LOGO.resize((LOGO.width * 2, LOGO.height * 2))) or monogram(520)
    if k > 0:
        Pk = P.rotate(4 * math.sin(t * 1.4), resample=Image.BICUBIC, expand=True)
        comp(img, Pk, (int(cx - Pk.width / 2), int(lerp(H, cy, k) - Pk.height / 2)))
    for i, key in enumerate(('b1', 'b2', 'b3')):          # benefit pills, alternating sides
        bk = back(seg(t, AT[key] - 0.1, AT[key] + 0.3), 1.3)
        if bk <= 0: continue
        txt = B['benefits'][i]; f = F('Bold', 46); tw = min(860, d.textlength(txt, font=f))
        y = 1170 + i * 120; x = lerp(-tw - 200 if i % 2 == 0 else W + 200, W / 2 - tw / 2 - 40, bk)
        d.rounded_rectangle([x, y - 46, x + tw + 120, y + 46], 46, fill=(0, 0, 0, 170), outline=C['p'] + (255,), width=4)
        d.ellipse([x + 18, y - 26, x + 70, y + 26], fill=C['p'] + (255,))
        d.line([(x + 30, y), (x + 41, y + 12), (x + 60, y - 12)], fill=contrast(C['p']), width=7)
        d.text((x + 92, y), txt, font=f, fill=C['a'], anchor='lm')

def scene_cta(img, t):
    t0 = AT['cta'] - 0.35; k = back(seg(t, t0, t0 + 0.45)); d = ImageDraw.Draw(img, 'RGBA')
    logo = LOGO or monogram(260)
    lk = eo(seg(t, t0, t0 + 0.4))
    if lk > 0:
        comp(img, logo, (int(W / 2 - logo.width / 2), int(lerp(200, 380, lk) - logo.height / 2)))
    if k > 0:
        p = 1 + 0.05 * math.sin(t * 7); bw, bh = 760 * k * p, 170 * k * p
        G = Image.new('RGBA', (W, H), (0, 0, 0, 0)); ImageDraw.Draw(G).rounded_rectangle([W / 2 - bw / 2, 900 - bh / 2, W / 2 + bw / 2, 900 + bh / 2], 90, fill=C['p'] + (200,))
        comp(img, G.filter(ImageFilter.GaussianBlur(24)))
        d.rounded_rectangle([W / 2 - bw / 2, 900 - bh / 2, W / 2 + bw / 2, 900 + bh / 2], 90, fill=C['p'])
        if k > 0.6: d.text((W / 2, 903), GOAL.get(B.get('goal', 'buy'), 'SHOP NOW'), font=F('Black', 84 * p), fill=contrast(C['p']), anchor='mm')
    if B.get('url'):
        uk = seg(t, t0 + 0.4, t0 + 0.8)
        d.text((W / 2, 1080), B['url'], font=F('Bold', 60), fill=C['a'] + (int(255 * uk),), anchor='mm')

def captions(img, t):
    for key, at in AT.items():
        words = VO[key]['text'].split(); d0 = VO[key]['dur']
        if not (at - 0.05 <= t <= at + d0 + 0.2): continue
        wl = [len(w) + 2 for w in words]; tot = sum(wl); acc, cur = 0, 0
        for i, w in enumerate(wl):
            if (t - at) / d0 * tot >= acc: cur = i
            acc += w
        lo = cur - cur % 4; chunk = words[lo:lo + 4]; d = ImageDraw.Draw(img, 'RGBA'); f = F('Black', 56); y = 1560
        tw = sum(d.textlength(w.upper() + ' ', font=f) for w in chunk)
        d.rounded_rectangle([W / 2 - tw / 2 - 26, y - 48, W / 2 + tw / 2 + 12, y + 46], 22, fill=(0, 0, 0, 165))
        x = W / 2 - tw / 2
        for j, w in enumerate(chunk):
            d.text((x, y), w.upper(), font=f, fill=C['p'] if lo + j == cur else (250, 250, 248), anchor='lm')
            x += d.textlength(w.upper() + ' ', font=f)
        return

def frame(t):
    img = background(t)
    if t < AT['b1'] - 0.5: scene_hook(img, t)
    elif t < AT['cta'] - 0.4: scene_product(img, t)
    else: scene_cta(img, t)
    for tw in (AT['b1'] - 0.5, AT['cta'] - 0.4):          # whip-pan flash between scenes
        k = seg(t, tw - 0.12, tw + 0.12)
        if 0 < k < 1: img = Image.blend(img, Image.new('RGB', (W, H), C['p']), 0.8 * math.sin(math.pi * k))
    captions(img, t)
    if B.get('watermark', True):
        ImageDraw.Draw(img, 'RGBA').text((W - 40, 1850), 'Made by TakeKash', font=F('Bold', 30), fill=(255, 255, 255, 150), anchor='rm')
    out = img
    fin = seg(t, DUR - 0.45, DUR)
    return Image.blend(out, Image.new('RGB', out.size, (0, 0, 0)), fin) if fin else out

# ---------------------------------------------------------------- audio
def score(out):
    import soundfile as sf
    from scipy.signal import butter, sosfilt, resample_poly
    SR = 44100; rng = np.random.default_rng(5); L = np.zeros((int(DUR * SR) + SR, 2), np.float32)
    def tt(d): return np.arange(int(d * SR)) / SR
    def flt(x, f, kind): return sosfilt(butter(2, f, kind, fs=SR, output='sos'), x).astype(np.float32)
    def add(sig, t, g=1.0):
        i = int(t * SR); n = min(len(sig), len(L) - i); L[i:i + n] += (sig[:n] * g)[:, None]
    def kick(): t = tt(0.4); return np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-t * 30)) / SR) * np.exp(-t * 8)
    def hat(): t = tt(0.05); return flt(rng.standard_normal(len(t)), 7000, 'high') * np.exp(-t * 90)
    def clap(): t = tt(0.2); return flt(rng.standard_normal(len(t)), [900, 3500], 'band') * np.exp(-t * 25)
    def riser(d): t = tt(d); return flt(rng.standard_normal(len(t)), 2500, 'high') * (t / d) ** 2
    bpm = 118; b = 60 / bpm
    for i in range(int(DUR / (b / 2))):
        tb = i * b / 2
        if tb > DUR - 1.0: break
        if i % 2 == 0: add(kick(), tb, 0.55)
        add(hat(), tb + b / 4, 0.07)
        if i % 4 == 2: add(clap(), tb, 0.18)
    t = tt(DUR); add((flt(np.sin(2 * np.pi * 55 * t) + 0.5 * np.sin(2 * np.pi * 82.4 * t), 300, 'low') * 0.08).astype(np.float32), 0)
    for tw in (AT['b1'] - 0.5, AT['cta'] - 0.4): add(riser(0.6), tw - 0.6, 0.25); add(kick(), tw, 0.9)
    vo = np.zeros(len(L), np.float32)
    for k, at in AT.items():
        a, sr = sf.read(os.path.join(out, 'vo', f'vo_{k}.wav'), dtype='float32')
        if a.ndim > 1: a = a.mean(1)
        if sr != SR: a = resample_poly(a, SR, sr).astype(np.float32)
        i = int(at * SR); vo[i:i + len(a)] += a[:len(vo) - i]
    env = np.convolve(np.abs(vo), np.ones(4410) / 4410, 'same'); L *= (1 - 0.5 * np.clip(env * 12, 0, 1))[:, None]
    L += vo[:, None]; L = L[:int(DUR * SR)]; L /= max(1e-6, np.abs(L).max() / 0.92)
    sf.write(os.path.join(out, 'score.wav'), L, SR)

# ---------------------------------------------------------------- render
def _part(args):
    brief, out, lo, hi = args
    load(brief, out); tmp = os.path.join(out, f'part_{lo:05d}.tmp.mp4')
    p = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                          '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p', tmp], stdin=subprocess.PIPE)
    for i in range(lo, hi): p.stdin.write(frame(i / FPS).tobytes())
    p.stdin.close(); p.wait()
    if p.returncode != 0: raise RuntimeError(f'ffmpeg failed for {lo}-{hi}')
    os.replace(tmp, os.path.join(out, f'part_{lo:05d}.mp4')); return lo

def main(brief, out, workers=2, stills_only=False):
    os.makedirs(out, exist_ok=True); b = json.load(open(brief))
    if not os.path.exists(os.path.join(out, 'vo', 'vo.json')):
        sys.path.insert(0, HERE); import voice
        voice.make(lines_of(b), style=VOICES.get(b.get('voice', 'female'), {}), out_dir=os.path.join(out, 'vo'))
    load(brief, out)
    if stills_only:
        for x in (AT['hook'] + 1.2, AT['b2'] + 0.8, AT['cta'] + 0.8):
            frame(x).save(os.path.join(out, f'still_{x:05.2f}.jpg'), quality=88)
        return
    n = int(DUR * FPS); cuts = [n * i // workers for i in range(workers + 1)]
    with Pool(workers) as pool: pool.map(_part, [(brief, out, cuts[i], cuts[i + 1]) for i in range(workers)])
    score(out)
    lst = os.path.join(out, 'parts.txt'); open(lst, 'w').write(''.join(f"file 'part_{c:05d}.mp4'\n" for c in cuts[:-1]))
    final = os.path.join(out, f"{slug(b['brand'])}-ad-9x16.mp4"); v = os.path.join(out, 'video.mp4')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', v], check=True)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', v, '-i', os.path.join(out, 'score.wav'), '-map', '0:v', '-map', '1:a',
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', final + '.tmp.mp4'], check=True)
    os.replace(final + '.tmp.mp4', final); print(final, DUR)
    return final

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], stills_only='--stills' in sys.argv)
