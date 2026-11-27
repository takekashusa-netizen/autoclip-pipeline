# Score for freead.py: run in the episode dir (vo/vo.json + vo/*.wav) -> score.wav (taiko cuts, stamps, hats, ducked voice)
import json, numpy as np, soundfile as sf
from scipy.signal import butter, sosfilt, resample_poly
SR = 44100; DUR = 23.11; rng = np.random.default_rng(3)
VO = json.load(open('vo/vo.json')); AT = {'hook': 0.9, 'steps': 3.75, 'build': 7.75, 'deliver': 14.75, 'cta': 17.45}
L = np.zeros((int(DUR * SR) + SR, 2), np.float32)
def tt(d): return np.arange(int(d * SR)) / SR
def flt(x, f, kind): return sosfilt(butter(2, f, kind, fs=SR, output='sos'), x).astype(np.float32)
def add(sig, t, g=1.0, pan=0.0):
    i = int(t * SR); n = min(len(sig), len(L) - i)
    L[i:i + n, 0] += sig[:n] * g * (1 - max(0, pan)); L[i:i + n, 1] += sig[:n] * g * (1 + min(0, pan))
def taiko(d=1.0, f0=110, f1=45):
    t = tt(d); ph = 2 * np.pi * np.cumsum(f1 + (f0 - f1) * np.exp(-t * 18)) / SR
    return (np.sin(ph) * np.exp(-t * 5) + flt(rng.standard_normal(len(t)), 900, 'low') * np.exp(-t * 30) * 0.5).astype(np.float32)
def hat(): t = tt(0.06); return flt(rng.standard_normal(len(t)), 7000, 'high') * np.exp(-t * 80)
def whoosh(d=0.5):
    t = tt(d); env = np.sin(np.pi * t / d) ** 2
    return flt(rng.standard_normal(len(t)), [400, 4000], 'band') * env
def stamp(): t = tt(0.25); return (flt(rng.standard_normal(len(t)), [150, 1500], 'band') * np.exp(-t * 28) * 1.6 + np.sin(2 * np.pi * 70 * t) * np.exp(-t * 14))
def slash():
    t = tt(0.6); s = flt(rng.standard_normal(len(t)), 3000, 'high') * np.exp(-t * 9)
    return s + np.sin(2 * np.pi * (2400 - 1800 * t) * t) * np.exp(-t * 7) * 0.3
# drone bed: minor fifth with slow swell, low pass
t = tt(DUR); bed = (np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 82.4 * t) + 0.3 * np.sin(2 * np.pi * 110 * t + np.sin(t * 0.7)))
bed *= (0.5 + 0.5 * np.minimum(1, t / 2.5)) * (1 - np.clip((t - (DUR - 1.2)) / 1.2, 0, 1)); add(flt(bed, 400, 'low').astype(np.float32), 0, 0.10)
add(slash(), 1.62, 0.55); add(taiko(1.4, 120, 40), 1.75, 1.0)
for x in (3.2, 7.2, 14.2, 16.9): add(whoosh(0.55), x, 0.35, pan=0.3)
for x in (5.3, 6.0, 6.7): add(stamp(), x, 0.8)
beat = 60 / 140                                         # build: hats + soft kicks
for i in range(int((14.4 - 7.75) / (beat / 2))):
    tb = 7.75 + i * beat / 2; add(hat(), tb, 0.10 if i % 2 else 0.06, pan=0.25 * (-1) ** i)
    if i % 4 == 0: add(taiko(0.5, 90, 50), tb, 0.35)
add(taiko(1.6, 140, 38), 14.75, 1.15); add(stamp(), 14.75, 0.9)
for i, x in enumerate((15.5, 15.75, 16.0, 16.25)): add(hat(), x, 0.12)
add(taiko(1.2, 110, 42), 17.45, 0.8); add(taiko(1.8, 100, 36), 21.3, 0.7)
# voice, with ducking under it
vo = np.zeros(len(L), np.float32)
for k, at in AT.items():
    a, sr = sf.read(f'vo/vo_{k}.wav', dtype='float32')
    if a.ndim > 1: a = a.mean(1)
    if sr != SR: a = resample_poly(a, SR, sr).astype(np.float32)
    i = int(at * SR); vo[i:i + len(a)] += a[:len(vo) - i]
env = np.convolve(np.abs(vo), np.ones(4410) / 4410, 'same'); duck = 1 - 0.45 * np.clip(env * 12, 0, 1)
L *= duck[:, None]; L += vo[:, None] * 1.05
L = L[:int(DUR * SR)]; L /= max(1e-6, np.abs(L).max() / 0.92)
sf.write('score.wav', L, SR)
print('ok', L.shape[0] / SR)
