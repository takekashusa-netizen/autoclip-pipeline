import json
import os
import subprocess
import sys

from celery import states
from celery.exceptions import Ignore

from worker.celery_app import app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBSTATE = [sys.executable, os.path.join(ROOT, "lib", "jobstate.py")]


def _run(cmd, cwd=ROOT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


@app.task(bind=True, name="pipeline.run_job", max_retries=2, default_retry_delay=30)
def run_job(self, job: str, format: str, skip_music: bool = False, force: bool = False):
    args = [os.path.join(ROOT, "run_pipeline.sh"), job, format]
    if skip_music:
        args.append("--skip-music")
    if force:
        args.append("--force")

    result = _run(args)

    if result.returncode != 0:
        self.update_state(
            state=states.FAILURE,
            meta={"job": job, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]},
        )
        try:
            self.retry(exc=RuntimeError(result.stderr[-2000:]))
        except self.MaxRetriesExceededError:
            raise Ignore()

    paused = "== paused:" in result.stdout
    return {
        "job": job,
        "format": format,
        "paused": paused,
        "stdout_tail": result.stdout[-2000:],
    }


@app.task(name="pipeline.approve_second_pass")
def approve_second_pass(job: str, format: str, skip_music: bool = False):
    r = _run(JOBSTATE + ["mark", job, "second_pass", "done"])
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return run_job.delay(job, format, skip_music=skip_music).id


@app.task(name="pipeline.to_premiere")
def to_premiere(job: str, format: str):
    args = [os.path.join(ROOT, "run_pipeline.sh"), job, format, "--to-premiere"]
    r = _run(args)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return {"job": job, "stdout_tail": r.stdout[-2000:]}


@app.task(name="pipeline.generate_thumbnail")
def generate_thumbnail(job: str, format: str, force: bool = False):
    env = os.environ.copy()
    if force:
        env["FORCE_THUMBNAIL"] = "1"
    r = subprocess.run(
        [os.path.join(ROOT, "skills", "thumbnail-generator", "run.sh"), job, format],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:])
    return {"job": job, "stdout_tail": r.stdout[-1000:]}


@app.task(name="pipeline.job_status")
def job_status(job: str):
    r = _run(JOBSTATE + ["path", job])
    path = r.stdout.strip()
    if not os.path.exists(path):
        return {"job": job, "exists": False}
    with open(path) as f:
        return json.load(f)
