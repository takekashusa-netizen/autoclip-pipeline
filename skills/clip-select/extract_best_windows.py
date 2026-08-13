#!/usr/bin/env python3
"""
skills/clip-select/extract_best_windows.py <rough_cut_video> <windows_json> <out_dir> <job_prefix>

Extracts each window found by best_windows.py as ONE single, continuous
ffmpeg cut — no fragment concatenation, no jump cuts, real unbroken
footage. Each window becomes its own file in out_dir, named
<job_prefix>_window01.mp4, _window02.mp4, etc. in chronological order.
"""
import json
import os
import subprocess
import sys


def run_ffmpeg(cmd, timeout_sec=1800):
    """Real bug fixed twice now: first, no timeout at all (the
    corrupted-source hang class found elsewhere tonight); then, a
    180-second default that was genuinely too short for a real 720-
    second (12-minute) re-encode from a large source file — confirmed
    directly: it killed a real, still-legitimately-working extraction
    mid-write on an actual job, producing a truncated/corrupt output
    ("moov atom not found") instead of ever letting it finish. 30
    minutes is generous enough for a real 12-minute veryfast re-encode
    even under heavy CPU contention, while still being a genuine bound
    against true infinite hangs, not an unbounded wait."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out after {timeout_sec}s — "
                            f"likely a corrupted/truncated region of the source") from e
    if result.returncode != 0:
        print(f"ffmpeg FAILED (exit {result.returncode}). Real stderr:\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


def main():
    rough_cut_video, windows_json_path, out_dir, job_prefix = sys.argv[1:5]
    os.makedirs(out_dir, exist_ok=True)

    with open(windows_json_path) as f:
        data = json.load(f)
    windows = data.get("windows", [])

    output_paths = []
    failures = []
    for i, w in enumerate(windows):
        out_path = os.path.join(out_dir, f"{job_prefix}_window{i+1:02d}.mp4")
        duration = w["end"] - w["start"]
        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-ss", str(w["start"]), "-i", rough_cut_video, "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            out_path, "-loglevel", "error",
        ]
        # Real bug fixed: one window's failure used to crash the WHOLE
        # script uncaught — confirmed directly on a real job, where
        # window01 timing out meant windows 2 and 3 were never even
        # attempted, silently leaving stale files from an earlier failed
        # run in their place with no indication anything was wrong. Now
        # a single window's failure is caught, logged clearly, and the
        # rest still get a real attempt — partial success beats a
        # silent total failure.
        try:
            run_ffmpeg(cmd)
            output_paths.append(out_path)
        except Exception as e:
            print(f"window {i+1} FAILED: {e}", file=sys.stderr)
            failures.append({"window": i + 1, "error": str(e)})
            if os.path.exists(out_path):
                os.remove(out_path)  # remove any partial/corrupt file rather than leave it looking real

    print(json.dumps({"extracted": len(output_paths), "paths": output_paths, "failures": failures}))
    if failures and not output_paths:
        sys.exit(1)  # every single window failed — that's a real, total failure, not a partial success


if __name__ == "__main__":
    main()
