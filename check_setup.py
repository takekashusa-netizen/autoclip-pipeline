#!/usr/bin/env python3
"""GtaxZombies clip studio: check everything the new tools need, and fix what's missing.

  python3 check_setup.py          # report only
  python3 check_setup.py --fix    # also install/upgrade what's missing (Homebrew + pip)

Run from your pipeline repo root, through safe_run.sh like your other commands.
"""
import os
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # hide harmless DNN backend warnings
import importlib, pathlib, shutil, subprocess, sys

FIX = "--fix" in sys.argv
ROOT = pathlib.Path.cwd()
problems = []

def ok(msg): print(f"  OK    {msg}")
def bad(msg, fix=None):
    print(f"  MISS  {msg}" + (f"\n        fix: {fix}" if fix else ""))
    problems.append((msg, fix))

def run(cmd):
    print(f"  ...   running: {cmd}")
    subprocess.run(cmd, shell=True, check=False)

print("\nSystem tools")
if sys.version_info >= (3, 9):
    ok(f"Python {sys.version.split()[0]}")
else:
    bad(f"Python {sys.version.split()[0]} is too old (need 3.9+)", "brew install python")

for tool in ("ffmpeg", "ffprobe"):
    if shutil.which(tool):
        ok(tool)
    else:
        bad(f"{tool} not found", "brew install ffmpeg")
        if FIX and shutil.which("brew"):
            run("brew install ffmpeg")

if shutil.which("ffmpeg"):
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    if " subtitles " in filters:
        ok("ffmpeg has libass (burned-in captions work)")
    else:
        bad("ffmpeg is missing libass, so captions can't be burned in", "brew reinstall ffmpeg")
        if FIX and shutil.which("brew"):
            run("brew reinstall ffmpeg")

print("\nPython packages")
try:
    cv2 = importlib.import_module("cv2")
    ok(f"opencv-python {cv2.__version__}")
    try:
        import numpy as np
        sys.path.insert(0, str(ROOT))
        from export_formats import make_detector
        detect = make_detector(320, 240)
        detect(np.zeros((240, 320, 3), np.uint8))
        kind = "YuNet" if hasattr(cv2, "FaceDetectorYN") and (ROOT / "assets/face_detection_yunet_2023mar.onnx").exists() else "Haar"
        ok(f"face detector works ({kind})")
    except SystemExit as e:
        bad(f"face detector unavailable: {e}", "put assets/face_detection_yunet_2023mar.onnx from the tools zip in place")
    except Exception as e:
        bad(f"face detector failed: {type(e).__name__}: {e}", "put assets/face_detection_yunet_2023mar.onnx from the tools zip in place")
except ImportError:
    bad("opencv-python not installed (needed by export_formats.py)", f"{sys.executable} -m pip install opencv-python")
    if FIX:
        run(f"{sys.executable} -m pip install opencv-python")

print("\nGtaxZombies tools in this folder")
def present(f):
    return (ROOT / f).exists() or (f.startswith("assets/") and (ROOT / f[7:]).exists())
for f in ("export_formats.py", "watermark_sample.py", "caption_fix.py",
          "assets/wm_logo_red.png", "assets/wm_endtag.png",
          "assets/face_detection_yunet_2023mar.onnx", "LICENSE"):
    (ok if present(f) else lambda m: bad(m, "put this file in the repo root (or assets/ for the images)"))(f)

print()
if problems:
    installable = [p for p in problems if p[1] and not p[1].startswith("put ")]
    msg = f"{len(problems)} item(s) need attention."
    if installable and not FIX:
        msg += " Run again with --fix to install the software ones."
    print(msg)
    sys.exit(1)
print("Everything is installed. All tools are ready.")
