#!/usr/bin/env python3
"""
lib/auto_metadata.py <job>

Generates title/description/tags the moment a job finishes and saves
them alongside the real output — ready for manual download+post, or
for any auto-upload path (YouTube/TikTok/Instagram), without needing
to regenerate anything per-platform. Reuses the same real generation
logic already built for YouTube (it's genuinely platform-agnostic text
generation, not YouTube-specific), so there's one real source of
title/description logic, not a separate copy per platform.

Writes <job>_metadata.json next to the real output in outputs/,
containing:
  title, description, tags, source_title, engagement_score,
  has_captions (whether this output has burned-in captions already)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # lib/ — for youtube_publish
sys.path.insert(0, ROOT)  # project root — for doctor.py
import doctor as doctor_mod  # noqa: E402 — reuses find_output_video / find_clip_metadata, not a copy
from youtube_publish import generate_title, generate_description, generate_tags  # noqa: E402


def has_burned_captions(job):
    """Real check, not a guess — short-clip formats burn captions in by
    default; long-form doesn't (relies on YouTube's own CC instead)."""
    job_json_path = os.path.join(ROOT, "projects", job, "job.json")
    if not os.path.exists(job_json_path):
        return None
    try:
        with open(job_json_path) as f:
            data = json.load(f)
        return data.get("steps", {}).get("captions", {}).get("status") == "done"
    except Exception:
        return None


def generate_and_save_metadata(job, content_type="gaming"):
    video_path = doctor_mod.find_output_video(job)
    if not video_path:
        return None  # not actually finished yet — nothing to generate metadata for
    clip_meta = doctor_mod.find_clip_metadata(job)
    if not clip_meta:
        return None  # not a recognized clip/montage subjob

    metadata = {
        "job": job,
        "title": generate_title(clip_meta, content_type),
        "description": generate_description(clip_meta, source_title=clip_meta.get("source_title")),
        "tags": generate_tags(clip_meta, content_type),
        "engagement_score": clip_meta.get("engagement_score"),
        "has_captions": has_burned_captions(job),
        "video_path": video_path,
    }
    out_path = os.path.join(ROOT, "outputs", f"{job}_metadata.json")
    with open(out_path, "w") as f:
        json.dump(metadata, f, indent=2)
    return metadata


def generate_metadata_for_all_finished_jobs(content_type="gaming"):
    """The real automatic hook — call this on a schedule (or from the
    background maintenance thread) to catch every job that finished
    since the last pass, without re-doing work for ones already done."""
    projects_dir = os.path.join(ROOT, "projects")
    if not os.path.isdir(projects_dir):
        return []
    generated = []
    for job in sorted(os.listdir(projects_dir)):
        out_path = os.path.join(ROOT, "outputs", f"{job}_metadata.json")
        if os.path.exists(out_path):
            continue  # already generated — don't redo work
        result = generate_and_save_metadata(job, content_type)
        if result:
            generated.append(job)
    return generated


def main():
    job = sys.argv[1]
    content_type = sys.argv[2] if len(sys.argv) > 2 else "gaming"
    result = generate_and_save_metadata(job, content_type)
    if result is None:
        print(json.dumps({"error": f"job '{job}' not finished or not a recognized clip/montage"}))
        sys.exit(1)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
