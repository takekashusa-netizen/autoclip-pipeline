"""Paths + model sources for the motion studio. Everything lives under MOTION_HOME
(default: <repo>/motion_work, git-ignored) so character art and voice files never get committed."""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = os.environ.get('MOTION_HOME', os.path.join(REPO, 'motion_work'))
MODELS = os.path.join(WORK, 'models')
VOICE_DIR = os.path.join(WORK, 'voice')
ASSETS = os.path.join(WORK, 'assets4')
OUT = os.path.join(WORK, 'out')
for d in (WORK, MODELS, VOICE_DIR, ASSETS, OUT): os.makedirs(d, exist_ok=True)

# All open-licensed, all on GitHub (no Hugging Face / PyTorch hosts needed)
SOURCES = {
    'kokoro.onnx': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx',   # Apache-2.0
    'voices.bin': 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin',
    'anime_x4.pth': 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth',  # BSD-3
}
MIN_BYTES = {'kokoro.onnx': 300_000_000, 'voices.bin': 20_000_000, 'anime_x4.pth': 15_000_000}

def model(name):
    """local path to a model, downloading it once (curl) and refusing truncated files"""
    import subprocess
    p = os.path.join(MODELS, name)
    if not os.path.exists(p) or os.path.getsize(p) < MIN_BYTES[name]:
        tmp = p + '.part'
        subprocess.run(['curl', '-fsSL', '-o', tmp, SOURCES[name]], check=True)
        if os.path.getsize(tmp) < MIN_BYTES[name]:
            raise RuntimeError(f'{name}: download incomplete ({os.path.getsize(tmp)} bytes)')
        os.replace(tmp, p)
    return p
