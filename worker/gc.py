import json
import os
import shutil
import time

from worker.celery_app import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects")
STALE_SECONDS = int(os.environ.get("PIPELINE_STALE_SECONDS", 7 * 24 * 3600))


@app.task(name="pipeline.gc_stale_jobs")
def gc_stale_jobs(dry_run: bool = False):
    removed = []
    if not os.path.isdir(PROJECTS):
        return {"removed": removed}

    now = time.time()
    for job in os.listdir(PROJECTS):
        job_dir = os.path.join(PROJECTS, job)
        job_json = os.path.join(job_dir, "job.json")
        if not os.path.isdir(job_dir) or not os.path.exists(job_json):
            continue

        mtime = os.path.getmtime(job_json)
        if now - mtime < STALE_SECONDS:
            continue

        finalized = False
        try:
            data = json.load(open(job_json))
            finalized = data.get("steps", {}).get("export", {}).get("status") == "done"
        except Exception:
            pass

        # only auto-remove jobs that finished and shipped — unfinished stale
        # jobs are left for a human to look at, not silently deleted
        if finalized:
            removed.append(job)
            if not dry_run:
                shutil.rmtree(job_dir, ignore_errors=True)

    return {"removed": removed, "dry_run": dry_run}


app.conf.beat_schedule = dict(app.conf.beat_schedule or {})
app.conf.beat_schedule["gc-stale-jobs-daily"] = {
    "task": "pipeline.gc_stale_jobs",
    "schedule": 24 * 3600,
}
