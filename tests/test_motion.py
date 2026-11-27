"""Fast checks for the Motion Studio (no model downloads)."""
import os, sys
import numpy as np
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'studio', 'motion'))

def test_extract_transparent_and_white(tmp_path, monkeypatch):
    monkeypatch.setenv('MOTION_HOME', str(tmp_path / 'w'))
    import extract
    sheet = np.zeros((300, 400, 4), np.uint8)
    sheet[20:120, 20:90] = (200, 30, 30, 255); sheet[150:280, 200:380] = (30, 30, 30, 255)
    p = tmp_path / 's.png'; Image.fromarray(sheet).save(p)
    made = extract.run(str(p), str(tmp_path / 'a'), upscale=False)
    assert sorted(made.values()) == [(70, 100), (180, 130)]
    white = np.full((300, 400, 3), 255, np.uint8); white[50:150, 60:160] = (20, 20, 20); white[70:130, 80:140] = (255, 255, 255)  # dark ring, white inside
    p2 = tmp_path / 'w.png'; Image.fromarray(white).save(p2)
    made2 = extract.run(str(p2), str(tmp_path / 'b'), upscale=False)
    assert list(made2.values()) == [(100, 100)]
    inner = np.asarray(Image.open(tmp_path / 'b' / 'part01.png'))[50, 50]
    assert inner[3] == 255 and inner[0] == 255          # white INSIDE the character (mask, trim) stays opaque

def test_onnx_graph_builds_from_weights(tmp_path):
    import upscale
    rs = np.random.RandomState(0)
    sd = {}
    def cw(k, o, i): sd[k + '.weight'] = rs.randn(o, i, 3, 3).astype(np.float32) * 0.01; sd[k + '.bias'] = np.zeros(o, np.float32)
    cw('conv_first', 8, 3)
    for r in (1, 2, 3):
        p = f'body.0.rdb{r}'
        cw(p + '.conv1', 4, 8); cw(p + '.conv2', 4, 12); cw(p + '.conv3', 4, 16); cw(p + '.conv4', 4, 20); cw(p + '.conv5', 8, 24)
    for k in ('conv_body', 'conv_up1', 'conv_up2', 'conv_hr'): cw(k, 8, 8)
    cw('conv_last', 3, 8)
    out = tmp_path / 'm.onnx'; upscale.build_onnx(sd, str(out))
    import onnxruntime as ort
    y = ort.InferenceSession(str(out)).run(None, {'input': np.zeros((1, 3, 10, 12), np.float32)})[0]
    assert y.shape == (1, 3, 40, 48)
