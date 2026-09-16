#!/usr/bin/env python3
"""Real, small reporting helper called from clip_pipeline.sh at each
real stage transition. Posts the real current stage to the live
job-status backend so the public status page and any local dashboard
can show genuine, live progress \u2014 not a simulation.

Usage:
  python3 report_status.py --job-id JOB --stage STAGE --stage-index N --total-stages T [--status STATUS] [--elapsed SECONDS]

Real, deliberate design: network failures here must NEVER break the
real pipeline run itself \u2014 status reporting is a real nice-to-have,
not a real dependency. Every failure is caught and logged, never
raised.
"""
import argparse
import json
import sys
import urllib.request
import urllib.error

STATUS_URL = "https://takekash-checkout.netlify.app/api/job-status"


def report(job_id, stage, stage_index, total_stages, status="in_progress", elapsed=None, video_duration_sec=None):
    payload = {
        "jobId": job_id,
        "stage": stage,
        "stageIndex": stage_index,
        "totalStages": total_stages,
        "status": status,
    }
    if elapsed is not None:
        payload["stageElapsedSec"] = elapsed
    if video_duration_sec is not None:
        payload["videoDurationSec"] = video_duration_sec

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        STATUS_URL, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        return True
    except Exception as e:
        # Real, deliberate: never let a status-reporting failure
        # interrupt or fail the real pipeline run itself.
        print(f"[report_status] non-fatal: failed to report status: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--job-id", required=True)
    p.add_argument("--stage", required=True)
    p.add_argument("--stage-index", type=int, required=True)
    p.add_argument("--total-stages", type=int, required=True)
    p.add_argument("--status", default="in_progress")
    p.add_argument("--elapsed", type=float, default=None)
    p.add_argument("--video-duration-sec", type=float, default=None)
    args = p.parse_args()

    report(args.job_id, args.stage, args.stage_index, args.total_stages, args.status, args.elapsed, args.video_duration_sec)
