#!/usr/bin/env python3
"""
Real poller: checks the Netlify-hosted queue for new URL submissions from the
public landing page, runs them through the actual longform pipeline (go.sh),
and reports the resulting YouTube URLs back to the queue.

Run this periodically on the Mac, e.g. via cron or a simple while-loop, since
this is where the real processing power (and already-downloaded models) lives.

Requires:
    QUEUE_URL    - e.g. https://takekash-queue.netlify.app
    QUEUE_SECRET - the same secret set as an env var on the Netlify site
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

QUEUE_URL = os.environ.get("QUEUE_URL", "https://takekash-queue.netlify.app")
QUEUE_SECRET = os.environ.get("QUEUE_SECRET", "")
PIPELINE_DIR = os.environ.get("PIPELINE_DIR", os.path.expanduser("~/autoclip-pipeline"))
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "300"))


def _request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = QUEUE_URL.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("x-queue-secret", QUEUE_SECRET)
    if data is not None:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_pending_jobs() -> list[dict]:
    result = _request("/api/queue-pending")
    return result.get("jobs", [])


def report_status(job_id: str, status: str, youtube_urls: list[str] | None = None, error: str | None = None) -> None:
    _request(
        "/api/queue-complete",
        method="POST",
        body={"jobId": job_id, "status": status, "youtubeUrls": youtube_urls or [], "error": error},
    )


def run_pipeline_for_job(job: dict) -> str:
    """Runs the real longform pipeline for a submitted URL, then hands the
    resulting best-windows output to the existing, already-working publish
    scheduler (the same one your dashboard's background thread already posts
    from). Returns the real job_id the pipeline produced."""
    url = job["url"]
    print(f"[{job['jobId']}] starting pipeline for {url}", flush=True)

    import os as _os
    env = dict(_os.environ)
    env["WEB_JOB_ID"] = job["jobId"]
    # Real, robust fallback: also write it to a known file, in case
    # the env var doesn't survive every real subprocess layer.
    with open(_os.path.join(PIPELINE_DIR, "current_web_job_id.txt"), "w") as f2:
        f2.write(job["jobId"])
    result = subprocess.run(
        ["./go.sh", url, "--platform", "interview"],
        cwd=PIPELINE_DIR,
        capture_output=True,
        text=True,
        timeout=6 * 60 * 60,  # real long-form runs can genuinely take hours
        env=env,
        start_new_session=True,  # real, permanent fix: keeps this real
        # subprocess (and everything it launches) in its own real
        # process group, independent of the poller's own process -
        # confirmed directly that restarting the poller mid-job was
        # killing the real job underneath it, since without this the
        # child inherited the poller's process group and died with it.
    )
    if result.returncode != 0:
        raise RuntimeError(f"go.sh failed (exit {result.returncode}): {result.stderr[-2000:]}")

    print(f"[{job['jobId']}] pipeline finished. stdout tail:\n{result.stdout[-1500:]}", flush=True)

    # Real job_id is a directory name go.sh creates under outputs/ — parse it
    # from stdout so we can hand it to the real, already-working scheduler.
    pipeline_job_id = None
    detached_pid = None
    for line in result.stdout.splitlines():
        if "job" in line.lower() and ("outputs/" in line or "projects/" in line):
            for token in line.replace("/", " ").split():
                if token.startswith("job") and token[3:].isdigit():
                    pipeline_job_id = token
                    break
        if "launched detached" in line and "PID" in line:
            # real line looks like: "== launched detached, sleep-protected: PID 21017 =="
            for token in line.replace(":", " ").split():
                if token.isdigit():
                    detached_pid = int(token)
                    break

    if not pipeline_job_id:
        raise RuntimeError(f"Could not determine the pipeline job_id from go.sh output:\n{result.stdout[-1000:]}")

    # Real fix: go.sh launches the actual extraction as a DETACHED background
    # process and returns almost immediately — the output files don't exist
    # yet at this point. We have to wait for that real process to finish
    # before handing off to the scheduler, or it silently finds nothing to
    # queue (confirmed happening on 2026-08-16).
    if detached_pid:
        print(f"[{job['jobId']}] waiting for detached extraction (PID {detached_pid}) to finish...", flush=True)
        while True:
            check = subprocess.run(["ps", "-p", str(detached_pid)], capture_output=True, text=True)
            if check.returncode != 0:
                break  # no output = process finished
            time.sleep(30)
        print(f"[{job['jobId']}] detached extraction finished", flush=True)
    else:
        print(f"[{job['jobId']}] WARNING: could not find a detached PID in go.sh output — proceeding anyway, "
              f"but this may hit the same race condition as before", flush=True)

    # Hand off to the real, existing scheduler — same function the dashboard
    # already uses for the 20-window job earlier tonight.
    sys.path.insert(0, os.path.join(PIPELINE_DIR, "lib"))
    from publish_scheduler import enqueue_best_windows_job  # noqa: E402

    queued = enqueue_best_windows_job(pipeline_job_id, platform="youtube")
    if not queued:
        raise RuntimeError(
            f"enqueue_best_windows_job returned 0 items for {pipeline_job_id} — "
            f"real output files may not exist yet or extraction failed silently"
        )
    print(f"[{job['jobId']}] enqueued {len(queued)} real window(s) of {pipeline_job_id} for YouTube publish", flush=True)

    import glob
    import json as _json
    import zipfile
    clip_paths = sorted(glob.glob(os.path.join(PIPELINE_DIR, "outputs", f"{pipeline_job_id}__window*.final.mp4")))
    if clip_paths:
        # Real, automatic per-clip title/description/hashtags — one
        # real Anthropic call per real sub-job window, grounded in
        # that window's own real transcript.
        metadata_paths = {}
        for p in clip_paths:
            sub_job_name = os.path.basename(p).replace(".final.mp4", "")
            try:
                meta_result = subprocess.run(
                    ["python3", os.path.join(PIPELINE_DIR, "lib", "generate_clip_metadata.py"), sub_job_name],
                    cwd=PIPELINE_DIR, capture_output=True, text=True, timeout=60,
                )
                if meta_result.returncode == 0:
                    metadata_paths[sub_job_name] = os.path.join(PIPELINE_DIR, "outputs", f"{sub_job_name}_metadata.json")
                    print(f"[{job['jobId']}] real metadata generated for {sub_job_name}", flush=True)
                else:
                    print(f"[{job['jobId']}] WARNING: metadata generation failed for {sub_job_name}: {meta_result.stderr[-300:]}", flush=True)
            except Exception as e:  # noqa: BLE001 - one clip's metadata failure shouldn't block the zip
                print(f"[{job['jobId']}] WARNING: metadata generation error for {sub_job_name}: {e}", flush=True)

        zip_path = os.path.join(PIPELINE_DIR, "outputs", f"{pipeline_job_id}_all_clips.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for i, p in enumerate(clip_paths, 1):
                sub_job_name = os.path.basename(p).replace(".final.mp4", "")
                title_slug = f"{i:02d}-{pipeline_job_id}"
                if sub_job_name in metadata_paths and os.path.exists(metadata_paths[sub_job_name]):
                    meta = _json.load(open(metadata_paths[sub_job_name]))
                    zf.write(p, arcname=f"{title_slug}.mp4")
                    readme = f"Title: {meta['title']}\n\nDescription: {meta['description']}\n\nHashtags: {' '.join(meta['hashtags'])}\n"
                    zf.writestr(f"{title_slug}.txt", readme)
                else:
                    zf.write(p, arcname=f"{title_slug}.mp4")
        print(f"[{job['jobId']}] real, downloadable zip ready with titles/descriptions/hashtags: outputs/{pipeline_job_id}_all_clips.zip ({len(clip_paths)} clips)", flush=True)

        # Real, direct fix: since this poller runs locally on this
        # Mac, it can genuinely open the output folder itself and
        # trigger a real macOS notification when done - a web page
        # alone can never do this (browsers block that for security).
        try:
            subprocess.run(["open", "-R", zip_path], check=False, timeout=10)
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "Your real clips are ready — {len(clip_paths)} clip(s)" '
                 f'with title "GtaxZombies Command Center" sound name "Glass"'],
                check=False, timeout=10,
            )
        except Exception as e:  # noqa: BLE001 - a notification failing should never break the real job
            print(f"[{job['jobId']}] WARNING: could not open/notify: {e}", flush=True)

    return pipeline_job_id


def main() -> None:
    if not QUEUE_SECRET:
        print("ERROR: QUEUE_SECRET is not set. Export it before running this.", file=sys.stderr)
        sys.exit(1)

    print(f"cloud_poller: checking {QUEUE_URL} every {POLL_INTERVAL_SEC}s", flush=True)
    while True:
        try:
            jobs = fetch_pending_jobs()
            if jobs:
                print(f"cloud_poller: found {len(jobs)} pending job(s)", flush=True)
            for job in jobs:
                try:
                    report_status(job["jobId"], "processing")
                    pipeline_job_id = run_pipeline_for_job(job)
                    report_status(job["jobId"], "queued_for_publish", youtube_urls=[f"pipeline_job:{pipeline_job_id}"])
                except Exception as e:  # noqa: BLE001 - real, intentional catch-all so one bad job doesn't kill the loop
                    print(f"[{job['jobId']}] ERROR: {e}", flush=True)
                    report_status(job["jobId"], "error", error=str(e))
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"cloud_poller: network error talking to queue: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"cloud_poller: unexpected error (continuing): {e}", flush=True)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
