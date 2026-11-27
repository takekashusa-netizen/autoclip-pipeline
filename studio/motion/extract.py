"""Split a character sheet into separate assets (transparent PNGs), then 4x-upscale them.
Works on transparent sheets (uses alpha) or white-background sheets (flood-fills the white from the edges).
With a preset (named boxes + erase rects) the output names are stable for the renderer."""
import json, os
import numpy as np, cv2
from PIL import Image

def alpha_of(rgba):
    if rgba.shape[2] == 4 and (rgba[..., 3] < 250).mean() > 0.05:
        return rgba[..., 3]
    rgb = rgba[..., :3]; h, w = rgb.shape[:2]
    near = (rgb.min(axis=2) > 232).astype(np.uint8) * 255
    m = np.zeros((h + 2, w + 2), np.uint8)
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if near[y, x] == 255: cv2.floodFill(near, m, (x, y), 128)
    return np.where(near == 128, 0, 255).astype(np.uint8)

def cut(rgba, box, erase=(), keep_all=False, min_area=3000):
    x0, y0, x1, y1 = box
    c = rgba[y0:y1, x0:x1].copy()
    m = (c[..., 3] > 30).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((3, 3), np.uint8)))
    if n > 1:
        keep = np.isin(lab, [i for i in range(1, n) if st[i, 4] > min_area]) if keep_all else (lab == 1 + np.argmax(st[1:, 4]))
        c[..., 3] = np.where(keep, c[..., 3], 0)
    h, w = c.shape[:2]
    for fx0, fy0, fx1, fy1 in erase:
        c[int(fy0 * h):int(fy1 * h), int(fx0 * w):int(fx1 * w), 3] = 0
    ys, xs = np.where(c[..., 3] > 10)
    return c[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

def auto_boxes(alpha, min_area=4000):
    n, lab, st, _ = cv2.connectedComponentsWithStats((alpha > 40).astype(np.uint8))
    return {f'part{i:02d}': (int(st[i, 0]), int(st[i, 1]), int(st[i, 0] + st[i, 2]), int(st[i, 1] + st[i, 3]))
            for i in range(1, n) if st[i, 4] > min_area}

def run(sheet, out_dir, preset=None, upscale=True):
    rgba = np.asarray(Image.open(sheet).convert('RGBA')).copy()
    rgba[..., 3] = alpha_of(rgba)
    P = json.load(open(preset)) if preset else {'boxes': auto_boxes(rgba[..., 3])}
    os.makedirs(out_dir, exist_ok=True); made = {}
    for name, box in P['boxes'].items():
        c = cut(rgba, box, P.get('erase', {}).get(name, ()), keep_all=name in P.get('keep_all', []))
        img = Image.fromarray(c)
        if upscale:
            from upscale import upscale_rgba
            img = upscale_rgba(img)
        img.save(os.path.join(out_dir, f'{name}.png')); made[name] = img.size
    return made
