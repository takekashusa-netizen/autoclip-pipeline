#!/usr/bin/env python3
"""
summarize_clips.py <job_prefix>

Pulls together everything the pipeline now tracks about a job's finished
clips into one clean report — real ffprobe-verified duration/size, plus
engagement score from clips.json where available. Built for the exact
moment a multi-clip job finishes: instead of manually ffprobing each
file and cross-referencing scores by hand, one command gives the full
picture.

Usage: python3 summarize_clips.py new881
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def ffprobe_duration(path, timeout_sec=30):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True, timeout=timeout_sec,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


def load_engagement_scores(job_prefix):
    """Checks every subjob's rough-cut/clips.json for engagement scores,
    keyed by clip id, so we can match them up with the actual output
    files even though the scores live in a different place than the
    finished .mp4s."""
    scores = {}
    projects_dir = os.path.join(ROOT, "projects")
    if not os.path.isdir(projects_dir):
        return scores
    for name in os.listdir(projects_dir):
        if not name.startswith(f"{job_prefix}__"):
            continue
        clips_json = os.path.join(projects_dir, job_prefix, "rough-cut", "clips.json")
        if not os.path.exists(clips_json):
            continue
        try:
            with open(clips_json) as f:
                data = json.load(f)
        except Exception:
            continue
        for c in data.get("clips", []):
            scores[f"{job_prefix}__{c['id']}"] = c.get("engagement_score")
        for m in data.get("montages", []):
            # montages don't have one score, they have per-segment scores —
            # report the average as the montage's overall score
            seg_scores = [s.get("engagement_score", 0) for s in m.get("segments", [])]
            if seg_scores:
                scores[f"{job_prefix}__{m['id']}"] = round(sum(seg_scores) / len(seg_scores))
    return scores


def main():
    if len(sys.argv) < 2:
        print("usage: python3 summarize_clips.py <job_prefix>")
        sys.exit(1)
    job_prefix = sys.argv[1]

    outputs_dir = os.path.join(ROOT, "outputs")
    if not os.path.isdir(outputs_dir):
        print(f"no outputs/ directory found")
        sys.exit(1)

    matches = sorted(
        f for f in os.listdir(outputs_dir)
        if f.startswith(f"{job_prefix}__") and f.endswith(".final.mp4")
    )
    single = f"{job_prefix}.final.mp4"
    if os.path.exists(os.path.join(outputs_dir, single)):
        matches = [single] + matches

    if not matches:
        print(f"no finished outputs found for '{job_prefix}' yet — check outputs/ once the job completes")
        sys.exit(0)

    scores = load_engagement_scores(job_prefix)

    print(f"\n=== {len(matches)} finished clip(s) for '{job_prefix}' ===\n")
    total_duration = 0.0
    total_size = 0
    rows = []
    for fname in matches:
        path = os.path.join(outputs_dir, fname)
        duration = ffprobe_duration(path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        clip_key = fname.replace(".final.mp4", "")
        score = scores.get(clip_key)

        total_duration += duration or 0
        total_size += size_mb

        rows.append((fname, duration, size_mb, score))

    name_width = max(len(r[0]) for r in rows) + 2
    print(f"{'file':<{name_width}}{'duration':<12}{'size':<10}{'engagement':<12}")
    print("-" * (name_width + 34))
    for fname, duration, size_mb, score in rows:
        dur_str = f"{duration:.1f}s" if duration else "invalid!"
        score_str = f"{score}/100" if score is not None else "n/a"
        print(f"{fname:<{name_width}}{dur_str:<12}{size_mb:.1f}MB{'':<5}{score_str:<12}")

    print("-" * (name_width + 34))
    print(f"total: {total_duration:.0f}s ({total_duration/60:.1f} min), {total_size:.0f}MB\n")

    invalid = [r[0] for r in rows if r[1] is None]
    if invalid:
        print(f"WARNING: {len(invalid)} file(s) failed ffprobe validation (possibly corrupt): {', '.join(invalid)}")


if __name__ == "__main__":
    main()
