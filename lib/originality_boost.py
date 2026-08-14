#!/usr/bin/env python3
"""
lib/originality_boost.py <input_video> <output_video> [seed_string]

Applies subtle, per-clip visual variation to reduce exact pixel/hash
duplication — the real mechanism behind "reduces content similarity and
increases originality rankings" that comparable commercial clipping
tools (Reka Clip and others) advertise. Real technique, not marketing:
platforms and re-upload detectors largely work off perceptual/pixel
hashing, so small, deterministic-per-clip variations (a slight zoom,
a slight color/contrast shift) change that fingerprint while staying
visually imperceptible to an actual viewer — nothing here is aggressive
enough to look distorted or hurt watchability.

seed_string (e.g. the job/clip name) makes the variation DETERMINISTIC
per clip — the same clip re-processed gets the same treatment, rather
than a different random result every run, while different clips from
the same source get genuinely different treatment from each other.
"""
import hashlib
import subprocess
import sys


def _seeded_value(seed_string, key, lo, hi):
    """Deterministic pseudo-random value in [lo, hi], derived from the
    seed string + a key — same seed always gives the same value, but
    different keys (zoom vs. saturation vs. contrast) get independent
    values instead of all moving in lockstep."""
    h = hashlib.sha256(f"{seed_string}:{key}".encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF  # 0.0-1.0
    return lo + frac * (hi - lo)


def build_filter(seed_string):
    """Real, subtle ranges — tested to stay imperceptible: zoom within
    1-3%, saturation/contrast shifts within a few percent. Nothing here
    should be visibly noticeable to an actual viewer."""
    zoom = _seeded_value(seed_string, "zoom", 1.01, 1.03)
    saturation = _seeded_value(seed_string, "saturation", 0.97, 1.03)
    contrast = _seeded_value(seed_string, "contrast", 0.98, 1.02)
    brightness = _seeded_value(seed_string, "brightness", -0.02, 0.02)

    return (
        f"scale=iw*{zoom:.4f}:ih*{zoom:.4f},"
        f"crop=iw/{zoom:.4f}:ih/{zoom:.4f},"
        f"eq=saturation={saturation:.4f}:contrast={contrast:.4f}:brightness={brightness:.4f}"
    ), {"zoom": zoom, "saturation": saturation, "contrast": contrast, "brightness": brightness}


def apply_originality_boost(input_path, output_path, seed_string, timeout_sec=1800):
    filter_str, params = build_filter(seed_string)
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-i", input_path,
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy",
        output_path, "-loglevel", "error",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"originality boost timed out after {timeout_sec}s") from e
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    return params


def main():
    input_path, output_path = sys.argv[1], sys.argv[2]
    seed_string = sys.argv[3] if len(sys.argv) > 3 else input_path
    params = apply_originality_boost(input_path, output_path, seed_string)
    import json
    print(json.dumps({"applied": True, "params": {k: round(v, 4) for k, v in params.items()}}))


if __name__ == "__main__":
    main()
