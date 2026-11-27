"""Poster prep: 2x anime upscale for the hero shots + a 'stage' plate (character removed, blurred, dark)."""
import json
import numpy as np, cv2
from PIL import Image, ImageFilter
import config
from upscale import upscale_rgba

def run(poster, preset=None):
    P = json.load(open(preset)) if preset else {}
    up = upscale_rgba(Image.open(poster).convert('RGB'), tile=256)
    up.resize((up.width // 2, up.height // 2), Image.LANCZOS).save(f'{config.WORK}/poster2x.png')
    img = cv2.imread(poster); h, w = img.shape[:2]
    if P.get('poster_polygon'):
        m = np.zeros((h, w), np.uint8); cv2.fillPoly(m, [np.array(P['poster_polygon'], np.int32)], 255)
        m = cv2.dilate(m, np.ones((31, 31), np.uint8))
        bg = cv2.inpaint(cv2.resize(img, (w // 4, h // 4)), cv2.resize(m, (w // 4, h // 4)), 15, cv2.INPAINT_TELEA)
        img = np.where(m[..., None] > 0, cv2.resize(bg, (w, h), interpolation=cv2.INTER_CUBIC), img)
    st = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).resize((1280, int(1280 * h / w)), Image.LANCZOS)
    st.filter(ImageFilter.GaussianBlur(5)).save(f'{config.WORK}/stage.png')
