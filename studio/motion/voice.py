"""The King voice: Kokoro (Apache-2.0) with a blended deep style, pitched down for presence.
lines = [(key, text), ...] -> <VOICE_DIR>/vo_<key>.wav + vo.json (text + exact durations)."""
import json, os
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
import config

DEFAULT = dict(voices={'am_onyx': 0.65, 'am_fenrir': 0.35}, semitones=-2.5, speed=1.0,
               say={'TakeKash': 'Take Cash', 'takekash.com': 'Take Cash dot com', 'GtaxZombies': 'G T A zombies'})

def make(lines, style=None, out_dir=None):
    from kokoro_onnx import Kokoro
    st = dict(DEFAULT); st.update(style or {})
    out_dir = out_dir or config.VOICE_DIR; os.makedirs(out_dir, exist_ok=True)
    k = Kokoro(config.model('kokoro.onnx'), config.model('voices.bin'))
    v = sum(k.get_voice_style(n) * w for n, w in st['voices'].items())
    up, down = 1000, int(round(1000 * 2 ** (st['semitones'] / 12)))
    meta = {}
    for key, txt in lines:
        spoken = txt
        for a, b in st['say'].items(): spoken = spoken.replace(a, b)
        a, sr = k.create(spoken, voice=v, speed=st['speed'], lang='en-us')
        a = resample_poly(np.asarray(a, np.float32), up, down).astype(np.float32)
        nz = np.where(np.abs(a) > 0.01)[0]; a = a[max(0, nz[0] - 800): nz[-1] + 3000]
        sf.write(os.path.join(out_dir, f'vo_{key}.wav'), a, sr)
        meta[key] = {'text': txt, 'dur': round(len(a) / sr, 3), 'sr': sr}
    json.dump(meta, open(os.path.join(out_dir, 'vo.json'), 'w'), indent=1)
    return meta
