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


def run_ffmpeg(cmd, timeout_sec=180):
    """Real bug fixed: no timeout — same corrupted-source hang class
    found twice tonight in different code paths; this new feature's
    single-continuous-cut extraction was equally exposed."""
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
    for i, w in enumerate(windows):
        out_path = os.path.join(out_dir, f"{job_prefix}_window{i+1:02d}.mp4")
        duration = w["end"] - w["start"]
        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-ss", str(w["start"]), "-i", rough_cut_video, "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
            out_path, "-loglevel", "error",
        ]
        run_ffmpeg(cmd)
        output_paths.append(out_path)

    print(json.dumps({"extracted": len(output_paths), "paths": output_paths}))


if __name__ == "__main__":
    main()
