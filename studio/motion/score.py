"""Soundtrack for the TakeKash samurai tour: taiko + koto (Karplus-Strong) + rain/thunder + sword FX,
with the king's narration processed (warmth, light compression, small hall) and music ducked under it."""
import sys, wave
import numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly, fftconvolve
sys.argv = ['x']
import tour as T, config

SR = 48000; DUR = T.DUR; N = int(SR * DUR)
music = np.zeros((N, 2), np.float32); vo = np.zeros((N, 2), np.float32)
rng = np.random.default_rng(7)
def tt(d): return np.arange(int(d * SR)) / SR
def noise(d): return rng.standard_normal(int(d * SR)).astype(np.float32)
def lp(x, f): return sosfilt(butter(2, f, 'low', fs=SR, output='sos'), x)
def hp(x, f): return sosfilt(butter(2, f, 'high', fs=SR, output='sos'), x)
def bp(x, a, b): return sosfilt(butter(2, [a, b], 'band', fs=SR, output='sos'), x)
def add(buf, sig, t, g=1.0, pan=0.0):
    i = int(t * SR); sig = np.asarray(sig, np.float32)
    if i >= N: return
    l, r = np.sqrt(.5 * (1 - pan)), np.sqrt(.5 * (1 + pan)); e = min(N, i + len(sig))
    buf[i:e, 0] += sig[:e - i] * g * l; buf[i:e, 1] += sig[:e - i] * g * r

def taiko(d=0.9, f0=95, f1=48):
    t = tt(d); f = f1 + (f0 - f1) * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.5)
    skin = lp(noise(d), 1200) * np.exp(-t * 30) * 0.5
    return body + skin
def shime(): t = tt(0.12); return bp(noise(0.12), 700, 3000) * np.exp(-t * 45) + np.sin(2 * np.pi * 420 * t) * np.exp(-t * 40) * 0.4
def koto(freq, d=1.8):
    n = int(SR / freq); buf = rng.uniform(-1, 1, n).astype(np.float32); out = np.zeros(int(d * SR), np.float32)
    for i in range(len(out)):
        out[i] = buf[i % n]; buf[i % n] = 0.996 * 0.5 * (buf[i % n] + buf[(i + 1) % n])
    return hp(out, 120) * 0.6
def ring(d=1.4):
    t = tt(d); s = sum(np.sin(2 * np.pi * f * t + p) * a for f, p, a in ((2093, 0, 0.5), (3371, 1, 0.35), (5210, 2, 0.25), (7040, 3, 0.15)))
    return s * np.exp(-t * 3.2)
def whoosh(d=0.5, a=300, b=5000): t = tt(d); return bp(noise(d), a, b) * np.sin(np.pi * t / d) ** 2
def thunder(d=3.5):
    t = tt(d); x = lp(noise(d), 180) * (np.exp(-t * 1.2) + 0.6 * np.exp(-((t - 0.25) ** 2) * 30))
    crack = hp(noise(0.25), 1500) * np.exp(-tt(0.25) * 18)
    x[:len(crack)] += crack * 0.6
    return x
def boom(d=2.0): t = tt(d); f = 30 + 60 * np.exp(-t * 6); return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6)
def shimmer(d=0.6): t = tt(d); f = 900 * 2 ** (t / d * 2); return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / d) * 0.3

# ---------------- bed: rain + low drone
rain = bp(noise(DUR), 1200, 9000) * 0.05 + lp(noise(DUR), 400) * 0.03
music[:, 0] += rain[:N]; music[:, 1] += np.roll(rain, 997)[:N]
t_all = tt(DUR)
drone = sum(np.sin(2 * np.pi * f * t_all + p) for f, p in ((73.4, 0), (73.9, 1), (110, 2), (146.8, 3))) * 0.045
drone = lp(drone, 600) * np.clip((t_all - 2.8) / 2, 0, 1)
music[:, 0] += drone; music[:, 1] += drone
for a, g in ((0.55, 0.9), (1.5, 0.6), (2.8, 1.0)): add(music, thunder(), a, g, -0.3)
add(music, boom(2.5), 3.4, 0.9)

# ---------------- groove: 84 BPM taiko ostinato from the intro to the gate
BEAT = 60 / 84
x = 3.4 + BEAT * 2; bi = 0
while x < T.LOCK0 - 0.2:
    if not (T.SLASH - 0.7 < x < T.SLASH + 0.6):
        if bi % 4 in (0, 2): add(music, taiko(), x, 0.75 if bi % 4 == 0 else 0.5, -0.1)
        if bi % 8 == 7: add(music, taiko(0.6, 120, 70), x + BEAT / 2, 0.4, 0.2)
        add(music, shime(), x + BEAT / 2, 0.12, 0.4)
    x += BEAT; bi += 1
# koto: D in-scale (D Eb G A Bb) phrases, one every 2 bars
SCALE = [146.8, 155.6, 196.0, 220.0, 233.1, 293.7, 311.1, 392.0]
phr = [[5, 4, 3, 2], [7, 5, 4, 5], [3, 2, 1, 0], [6, 5, 3, 4]]
x = 4.0; pi_ = 0
while x < T.LOCK0 - 1:
    for j, n in enumerate(phr[pi_ % 4]): add(music, koto(SCALE[n]), x + j * BEAT / 2, 0.16, (j - 1.5) * 0.3)
    x += BEAT * 8; pi_ += 1

# ---------------- sword + scene FX
add(music, whoosh(0.4, 200, 3000), T.SLASH - 0.95, 0.3)
add(music, hp(noise(0.5), 2500) * np.exp(-tt(0.5) * 6) * 0.4 + ring(0.5)[:int(0.5 * SR)] * 0.2, T.SLASH - 0.6, 0.6)   # draw scrape
add(music, ring(1.6), T.SLASH - 0.55, 0.35, 0.2)
add(music, whoosh(0.35, 800, 9000), T.SLASH - 0.28, 0.8, -0.4)
add(music, boom(2.2), T.SLASH, 1.0); add(music, hp(noise(0.15), 2000) * np.exp(-tt(0.15) * 30), T.SLASH, 0.6)
add(music, ring(2.0), T.SLASH + 0.02, 0.3, -0.2)
for k, a, b, p in T.STOPS: add(music, shimmer(), a, 0.5, 0.5 if p[0] > 0 else -0.5)
add(music, boom(2.0), T.GATE0 + 0.1, 0.8)
for d_ in (0.4, 1.4): add(music, whoosh(0.45, 300, 4000), T.GATE0 + d_, 0.5)
add(music, thunder(2.5), T.LOCK0 - 0.1, 0.6)
add(music, boom(3.0), T.LOCK0, 1.0); add(music, taiko(1.2, 80, 40), T.LOCK0, 0.9)
sz = bp(noise(1.8), 3000, 11000) * np.linspace(1, 0, int(1.8 * SR)) ** 2; add(music, sz, T.LOCK0 + 0.3, 0.35)   # forge cooling hiss
for d_ in (1.8, 2.3): add(music, taiko(), T.LOCK0 + d_, 0.7)
pt = tt(DUR - T.LOCK0); pad = lp(sum(np.sin(2 * np.pi * f * pt) for f in (73.4, 110, 146.8, 174.6, 220)) * 0.06, 1200)
add(music, pad * np.clip(pt / 0.5, 0, 1), T.LOCK0, 1.0)

# ---------------- the king's voice
IR = (noise(0.7) * np.exp(-tt(0.7) * 7)).astype(np.float32); IR = lp(IR, 5000); IR /= np.abs(IR).sum() ** 0.5 * 8
duck = np.zeros(N, np.float32)
for key, at in T.VO_AT.items():
    a, sr = sf.read(f'{T.TTS}/vo_{key}.wav', dtype='float32')
    a = resample_poly(a, SR, sr).astype(np.float32)
    low = lp(a, 180); a = a + low * 0.5                                   # chest warmth
    a = a + hp(a, 3000) * 0.25                                           # presence
    env = np.sqrt(np.convolve(a ** 2, np.ones(480) / 480, 'same')) + 1e-4
    gain = np.minimum(1.0, (0.12 / env) ** 0.45); a = a * gain            # gentle compression
    wet = fftconvolve(a, IR)[:len(a) + len(IR) - 1]
    sig = np.concatenate([a, np.zeros(len(IR) - 1, np.float32)]) + wet * 0.35
    add(vo, sig, at, 1.0)
    i0 = int((at - 0.15) * SR); i1 = min(N, int((at + len(a) / SR + 0.25) * SR)); duck[max(0, i0):i1] = 1
k = int(0.12 * SR); duck = np.convolve(duck, np.ones(k) / k, 'same')
music *= (1 - 0.6 * duck)[:, None]
vo /= max(1e-6, np.abs(vo).max()); vo *= 0.95
music /= max(1e-6, np.abs(music).max()); music *= 0.75
mix = np.tanh((music + vo) * 1.05) * 0.92
fs_ = int((DUR - 0.8) * SR); mix[fs_:] *= np.linspace(1, 0, N - fs_)[:, None]
mix /= max(1e-6, np.abs(mix).max() / 0.89)
with wave.open(f'{config.OUT}/tour.wav', 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((mix * 32767).astype('<i2').tobytes())
print('tour audio ok', DUR)
