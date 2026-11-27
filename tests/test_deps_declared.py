"""Guard: every third-party module imported by tests/ and the code they exercise must be in requirements-dev.txt,
so CI (a clean machine) can never fail with 'No module named X' again."""
import ast, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = ["tests", "lib", "studio", "studio.py", "motion.py"]
PKG = {"cv2": "opencv-python-headless", "PIL": "pillow", "onnxruntime": "onnxruntime", "yaml": "pyyaml",
       "multipart": "python-multipart", "skimage": "scikit-image", "sklearn": "scikit-learn"}
OPTIONAL = {"anthropic", "openai", "whisper", "faster_whisper", "torch", "kokoro_onnx", "googleapiclient", "google",
            "redis", "celery", "playwright", "boto3", "tesserocr", "matplotlib",
            "yt_dlp", "google_auth_oauthlib", "stripe"}   # imported lazily, guarded with try


def _local_names():
    names = set()
    for d, _, fs in os.walk(ROOT):
        if "/.git" in d or "node_modules" in d: continue
        names.add(os.path.basename(d))
        names.update(f[:-3] for f in fs if f.endswith(".py"))
    return names


def _imports():
    out = {}
    for s in SCAN:
        p = os.path.join(ROOT, s)
        files = [p] if p.endswith(".py") else [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs if f.endswith(".py")]
        for f in files:
            try: tree = ast.parse(open(f, encoding="utf-8").read())
            except SyntaxError: continue
            for n in ast.walk(tree):
                if isinstance(n, ast.Import): mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module: mods = [n.module]
                else: continue
                for m in mods: out.setdefault(m.split(".")[0], os.path.relpath(f, ROOT))
    return out


def test_third_party_imports_are_declared():
    req = {l.split("==")[0].strip().lower() for l in open(os.path.join(ROOT, "requirements-dev.txt")) if l.strip() and not l.startswith("#")}
    local = _local_names()
    missing = {}
    for mod, where in _imports().items():
        if mod in sys.stdlib_module_names or mod in local or mod in OPTIONAL or mod == "__future__": continue
        if PKG.get(mod, mod).lower().replace("_", "-") not in {r.replace("_", "-") for r in req}:
            missing[mod] = where
    assert not missing, f"add to requirements-dev.txt (or OPTIONAL if lazily guarded): {missing}"
