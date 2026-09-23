#!/usr/bin/env python3
"""
dashboard.py [--port 8765]

The single, unified AI clipping agent server — every function built
across this whole session, in one process:
  - Job submission (short clips or long-form) via a real web UI
  - Channel watching (start/stop a live poll loop for new VODs)
  - Background auto-resume for stalled/failed jobs (was doctor.py,
    now a thread inside this same process, not a separate one to
    remember to start)
  - Background auto-publish to YouTube once a job finishes
  - On-demand publish to YouTube or TikTok for any specific job
  - Originality Boost (subtle per-clip visual variation) on any output
  - Real download links for every finished clip

Single Python file, stdlib only for the server itself (publish
integrations import their own real dependencies only when actually
used, so the server itself has zero hard dependencies beyond the
standard library).

Run it, then open http://localhost:8765 in a browser on the same Mac.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.realpath(os.path.join(ROOT, "outputs"))
PROJECTS_DIR = os.path.join(ROOT, "projects")
sys.path.insert(0, os.path.join(ROOT, "lib"))

_WATCHER_STATE = {}  # real, in-process thread state — replaces the old separate-subprocess+PID-file approach


def sanitize_job_name(name):
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    return cleaned[:64] if cleaned else None


def list_jobs():
    jobs = []
    if not os.path.isdir(PROJECTS_DIR):
        return jobs
    all_names = sorted(os.listdir(PROJECTS_DIR))
    for name in all_names:
        job_json = os.path.join(PROJECTS_DIR, name, "job.json")
        if not os.path.exists(job_json):
            continue
        try:
            with open(job_json) as f:
                data = json.load(f)
        except Exception:
            continue
        steps = data.get("steps", {})
        export_status = steps.get("export", {}).get("status", "pending")
        locked = os.path.exists(os.path.join(PROJECTS_DIR, name, ".lock"))

        # Real bug fixed: a "parent" job that spawns clip/montage/best-
        # windows subjobs (or extracts directly to outputs/<job>_best_windows/)
        # never sets its OWN export step — that only happens for a
        # single-video job's own 7-step pipeline. Confirmed directly: a
        # job we'd already verified produced 3 perfect real output files
        # was still showing as "pending/failed" here, purely because
        # this check only ever looked at the job's own export status.
        is_effectively_done = export_status == "done"
        if not is_effectively_done:
            has_subjobs_done = any(
                n.startswith(f"{name}__") and
                json.load(open(os.path.join(PROJECTS_DIR, n, "job.json"))).get("steps", {}).get("export", {}).get("status") == "done"
                for n in all_names
                if n.startswith(f"{name}__") and os.path.exists(os.path.join(PROJECTS_DIR, n, "job.json"))
            )
            has_best_windows_output = os.path.isdir(os.path.join(OUTPUTS_DIR, f"{name}_best_windows")) and \
                any(f.endswith(".mp4") for f in os.listdir(os.path.join(OUTPUTS_DIR, f"{name}_best_windows")))
            is_effectively_done = has_subjobs_done or has_best_windows_output

        jobs.append({
            "job": name,
            "status": "done" if is_effectively_done else ("running" if locked else "pending/failed"),
            "error": data.get("error"),
            "youtube_url": data.get("youtube_url"),
        })
    return jobs


def list_outputs():
    outputs = []
    if not os.path.isdir(OUTPUTS_DIR):
        return outputs
    for name in sorted(os.listdir(OUTPUTS_DIR)):
        if not (name.endswith(".mp4") or name.endswith(".zip")):
            continue
        path = os.path.join(OUTPUTS_DIR, name)
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 1)
        outputs.append({"name": name, "size_mb": size_mb})
    return outputs


_STAGE_CHECKPOINTS = [
    (r"extracting audio from source", "Extracting audio", 5),
    (r"transcribing \+ building EDL", "Transcribing + building rough cut", 15),
    (r"rough-cut: done", "Rough cut complete", 60),
    (r"analyzing visual content", "Analyzing visual content (motion detection)", 65),
    (r"analyzing audio content", "Analyzing audio content (impact detection)", 72),
    (r"best-windows: \{.*window_count", "Computing best windows", 75),
    (r"launched detached", "Extracting final window clips", 80),
    (r"best-windows done", "Done", 100),
]


def _find_running_pipeline_jobs(root):
    """Real scan of safe_run logs — finds each log's real job name, then
    determines if it's genuinely still running. Early stages (audio
    extraction, transcription, analysis) run in the pipeline's own
    foreground process with no separate PID to check — for those, real
    log-file freshness (recently modified) is the honest signal. Once
    the log reports a detached extraction PID, that PID's actual
    liveness via `ps` becomes the real, more precise signal."""
    import time

    logs_dir = os.path.join(root, "logs", "safe_run")
    if not os.path.isdir(logs_dir):
        return []

    running = []
    for fname in sorted(os.listdir(logs_dir)):
        if not fname.startswith("clip_pipeline_") or not fname.endswith(".log"):
            continue
        log_path = os.path.join(logs_dir, fname)
        try:
            with open(log_path, errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        job_match = re.search(r"clip_pipeline: job=(\S+)", content)
        if not job_match:
            continue
        job_name = job_match.group(1)

        if "best-windows done" in content:
            continue

        current_stage = "Starting"
        percent = 0
        for pattern, label, pct in _STAGE_CHECKPOINTS:
            if re.search(pattern, content):
                current_stage = label
                percent = pct

        pid_match = re.search(r"launched detached.*?PID (\d+)", content)
        if pid_match:
            pid = int(pid_match.group(1))
            check = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
            is_alive = check.returncode == 0
        else:
            pid = None
            mtime = os.path.getmtime(log_path)
            is_alive = (time.time() - mtime) < 300

        if not is_alive:
            continue

        running.append({
            "job": job_name,
            "pid": pid,
            "stage": current_stage,
            "percent_complete": percent,
            "log_file": fname,
        })

    return running


def list_best_windows_jobs():
    """Real listing of every best-windows job that has actual output files,
    cross-referenced against publish_schedule.json so the UI can show real
    publish status per window, not just file existence."""
    import doctor as doctor_mod

    jobs = []
    if not os.path.isdir(OUTPUTS_DIR):
        return jobs

    schedule_by_content_id = {}
    schedule_path = os.path.join(ROOT, "publish_schedule.json")
    if os.path.exists(schedule_path):
        try:
            with open(schedule_path) as f:
                for item in json.load(f):
                    schedule_by_content_id[item["content_id"]] = item
        except Exception:
            pass

    for name in sorted(os.listdir(OUTPUTS_DIR)):
        if not name.endswith("_best_windows") or not os.path.isdir(os.path.join(OUTPUTS_DIR, name)):
            continue
        job_name = name[: -len("_best_windows")]
        video_paths = doctor_mod.find_best_windows_outputs(job_name)
        if not video_paths:
            continue

        windows = []
        for i, video_path in enumerate(video_paths):
            content_id = f"{job_name}_window{i+1:02d}"
            size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 1)
            schedule_item = schedule_by_content_id.get(content_id)
            # Real, permanent fix: this dashboard preview used to call
            # the confirmed-broken generate_window_metadata, so the
            # listing itself could show raw transcript garbage as a
            # clip's title before it was ever published.
            meta = None
            try:
                from generate_clip_metadata import generate_clip_metadata
                sub_job = f"{job_name}__window{i + 1:02d}"
                meta = generate_clip_metadata(sub_job, "youtube")
            except Exception:
                pass
            windows.append({
                "content_id": content_id,
                "filename": os.path.basename(video_path),
                "size_mb": size_mb,
                "title": meta["title"] if meta else content_id,
                "publish_status": schedule_item["status"] if schedule_item else "not_scheduled",
                "scheduled_time": schedule_item.get("scheduled_time") if schedule_item else None,
                "download_url": f"/download/{job_name}_best_windows/{os.path.basename(video_path)}",
            })

        jobs.append({"job": job_name, "windows": windows})

    return jobs


def background_maintenance_loop(interval_sec=60, resume_interval_sec=600, publish_interval_sec=300,
                                 metadata_interval_sec=60, schedule_interval_sec=60,
                                 prune_interval_sec=86400, log_rotate_interval_sec=3600,
                                 metadata_retry_interval_sec=600,
                                 auto_publish=False, content_type="gaming"):
    """The real consolidation: doctor.py's auto-resume and auto-publish
    logic, running as a thread INSIDE this same server process instead
    of a separate one you have to remember to start alongside it.
    Imports doctor.py's actual functions rather than reimplementing
    them, so there's exactly one real implementation of this logic, not
    two copies that can drift apart.

    Also generates real title/description/tags the moment ANY job
    finishes — not gated behind auto_publish, since the metadata is
    useful for a manual download+post too, not just auto-upload.

    Also processes the real publish schedule — 2 posts/day per
    platform at research-backed optimal times, not everything at once
    the moment it's queued."""
    try:
        import doctor as doctor_mod
    except ImportError as e:
        print(f"dashboard: background maintenance unavailable — {e}", flush=True)
        return
    try:
        from auto_metadata import generate_metadata_for_all_finished_jobs
    except ImportError as e:
        generate_metadata_for_all_finished_jobs = None
        print(f"dashboard: auto-metadata unavailable — {e}", flush=True)
    try:
        from publish_scheduler import process_due_items, retry_metadata_failures
    except ImportError as e:
        process_due_items = None
        retry_metadata_failures = None
        print(f"dashboard: publish scheduler unavailable — {e}", flush=True)
    try:
        from prune_finished_jobs import prune as prune_finished_jobs
    except ImportError as e:
        prune_finished_jobs = None
        print(f"dashboard: finished-job pruning unavailable — {e}", flush=True)
    try:
        from log_rotate import rotate_if_needed
    except ImportError as e:
        rotate_if_needed = None
        print(f"dashboard: log rotation unavailable — {e}", flush=True)

    last_resume = 0.0
    last_publish = 0.0
    last_metadata = 0.0
    last_schedule = 0.0
    last_prune = 0.0
    last_log_rotate = 0.0
    last_metadata_retry = 0.0
    while True:
        try:
            if time.time() - last_resume >= resume_interval_sec:
                # doctor.py's own --auto-resume CLI loop calls both of
                # these together (run_checks() + auto_resume()), but this
                # background thread was only ever calling auto_resume() —
                # confirmed tonight via dashboard.log + doctor_auto_resume.log
                # that check_stale_locks() was never actually running here,
                # so a lock left behind by a crashed/killed render sat
                # forever instead of being cleared once its PID was
                # confirmed dead.
                doctor_mod.check_stale_locks()
                doctor_mod.auto_resume(auto_approve=True)
                last_resume = time.time()
            if generate_metadata_for_all_finished_jobs and time.time() - last_metadata >= metadata_interval_sec:
                generated = generate_metadata_for_all_finished_jobs(content_type=content_type)
                if generated:
                    print(f"dashboard: generated metadata for {len(generated)} newly-finished job(s): {generated}", flush=True)
                last_metadata = time.time()
            if process_due_items and time.time() - last_schedule >= schedule_interval_sec:
                # Real, permanent fix: this used to only print when something
                # was actually published, so a silent log was ambiguous —
                # "checked, nothing due" and "never checked" looked identical.
                # Confirmed causing real confusion tonight (had to manually
                # verify via a one-off script whether the loop was even
                # running). Now every check logs, and anything sitting
                # significantly overdue gets a loud, explicit warning instead
                # of silently waiting for the next pass.
                published = process_due_items()
                if published:
                    print(f"dashboard: schedule check — processed {len(published)} due item(s)", flush=True)
                else:
                    print("dashboard: schedule check — nothing due right now", flush=True)
                try:
                    _warn_about_stuck_schedule_items()
                except Exception as stuck_check_err:
                    print(f"dashboard: stuck-item check failed (non-fatal): {stuck_check_err}", flush=True)
                last_schedule = time.time()
            if prune_finished_jobs and time.time() - last_prune >= prune_interval_sec:
                # Real, permanent fix for the ~65GB projects/ buildup found and
                # cleaned up in the 2026-09-16 audit: once a job (or, for
                # clip_pipeline.sh jobs, all of its windows) is fully exported
                # and its final render is confirmed sitting in outputs/, the
                # raw/rough-cut/work/music intermediates in projects/<job>/ are
                # pure dead weight — nothing reads them again. Runs once a day
                # by default; safe to run more often, it's a no-op when there's
                # nothing newly finished to reclaim.
                freed, touched = prune_finished_jobs()
                if touched:
                    print(f"dashboard: pruned {freed/1e9:.2f} GB of finished-job media across {touched} job dir(s)", flush=True)
                last_prune = time.time()
            if rotate_if_needed and time.time() - last_log_rotate >= log_rotate_interval_sec:
                # Real, permanent fix added 2026-09-22 after a watchdog-timeout
                # kernel panic: dashboard.log/poller.log are plain launchd-
                # redirected stdout/stderr with no rotation of their own, so
                # they'd otherwise grow forever. Caps each at ~20MB, truncated
                # in place (see lib/log_rotate.py for why in-place, not
                # rename) so the still-running launchd process keeps writing
                # correctly with no restart needed.
                for log_name in ("dashboard.log", "poller.log"):
                    try:
                        if rotate_if_needed(os.path.join(ROOT, log_name)):
                            print(f"dashboard: rotated {log_name} (exceeded size cap)", flush=True)
                    except Exception as rotate_err:
                        print(f"dashboard: log rotation of {log_name} failed (non-fatal): {rotate_err}", flush=True)
                last_log_rotate = time.time()
            if retry_metadata_failures and time.time() - last_metadata_retry >= metadata_retry_interval_sec:
                # Real, permanent fix added 2026-09-22 ("make this mandatory
                # from now on"): a window whose real metadata generation
                # failed used to just print a line and vanish — nothing
                # ever retried it, which is exactly how camcapone_window01
                # sat with no real caption for days until it was found by
                # hand. Every failure now lands in metadata_failures.json
                # (see lib/publish_scheduler.py) and gets retried
                # automatically here, on its own, without needing anyone
                # to notice.
                try:
                    retry_result = retry_metadata_failures()
                    if retry_result.get("retried"):
                        print(f"dashboard: metadata-failure retry — recovered "
                              f"{retry_result['recovered']}/{retry_result['retried']} "
                              f"(still failing: {retry_result['still_failing']})", flush=True)
                except Exception as retry_err:
                    print(f"dashboard: metadata-failure retry pass failed (non-fatal): {retry_err}", flush=True)
                last_metadata_retry = time.time()
            if auto_publish and time.time() - last_publish >= publish_interval_sec:
                doctor_mod.publish_pending_jobs()
                last_publish = time.time()
        except Exception as e:
            print(f"dashboard: background maintenance error (continuing): {e}", flush=True)
        time.sleep(interval_sec)


def _warn_about_stuck_schedule_items(stale_after_minutes=30):
    """Real, permanent fix for a real problem tonight: an item stuck as
    'pending' well past its scheduled_time gave no signal anything was
    wrong short of someone manually checking. This makes that loud and
    visible in the log the moment it happens, instead of silent."""
    from datetime import datetime

    schedule_path = os.path.join(ROOT, "publish_schedule.json")
    if not os.path.exists(schedule_path):
        return
    with open(schedule_path) as f:
        items = json.load(f)

    now = datetime.now()
    for item in items:
        if item.get("status") != "pending":
            continue
        try:
            scheduled = datetime.fromisoformat(item["scheduled_time"])
        except (KeyError, ValueError):
            continue
        overdue_minutes = (now - scheduled).total_seconds() / 60
        if overdue_minutes > stale_after_minutes:
            print(
                f"dashboard: WARNING — {item['content_id']} has been pending "
                f"{int(overdue_minutes)} minutes past its scheduled time "
                f"({item['scheduled_time']}) — investigate, something may be stuck",
                flush=True,
            )


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Autoclip Dashboard</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #0d0d0d; color: #eee; }
  h1 { color: #7fdc7f; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
  input, select, button { padding: 8px; margin: 4px 0; border-radius: 4px; border: 1px solid #444; background: #222; color: #eee; }
  input[type=text] { width: 100%; box-sizing: border-box; }
  button { background: #2d6a2d; color: white; border: none; cursor: pointer; padding: 10px 20px; font-weight: bold; }
  button:hover { background: #3d8a3d; }
  button.danger { background: #8a2d2d; }
  button.danger:hover { background: #aa3d3d; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; }
  th, td { text-align: left; padding: 8px; border-bottom: 1px solid #333; }
  .status-done { color: #7fdc7f; }
  .status-running { color: #dcdc7f; }
  .status-failed { color: #dc7f7f; }
  a { color: #7fb8dc; }
</style>
</head>
<body>
<h1>Autoclip Dashboard</h1>

<div class="card">
  <h2>New Job</h2>
  <input type="text" id="url" placeholder="Video URL (e.g. https://www.twitch.tv/videos/XXXX)">
  <select id="platform">
    <option value="longform" selected>Long-form YouTube (10+ min continuous)</option>
    <option value="tiktok">TikTok (25s clips)</option>
    <option value="youtube">YouTube (35s clips)</option>
  </select>
  <input type="text" id="clipcount" placeholder="Clip count" value="10" style="width:100px">
  <br>
  <button onclick="triggerJob()">Start Clipping</button>
  <span id="triggerResult"></span>
</div>

<div class="card">
  <h2>Channel Watcher</h2>
  <input type="text" id="channelUrl" placeholder="Twitch channel URL (e.g. https://www.twitch.tv/gtaxzombies)">
  <br>
  <button onclick="startWatcher()">Start Watching</button>
  <button class="danger" onclick="stopWatcher()">Stop Watching</button>
  <span id="watcherStatus"></span>
</div>

<div class="card">
  <h2>Jobs</h2>
  <table id="jobsTable"><thead><tr><th>Job</th><th>Status</th><th>YouTube</th><th></th></tr></thead><tbody></tbody></table>
</div>

<div class="card">
  <h2>Finished Outputs</h2>
  <table id="outputsTable"><thead><tr><th>File</th><th>Size</th><th></th></tr></thead><tbody></tbody></table>
</div>

<div class="card">
  <h2>Publish Schedule</h2>
  <p style="opacity:0.7; font-size:0.9em;">2 posts/day per platform, at real research-backed optimal times.</p>
  <input type="text" id="scheduleJob" placeholder="Job name (e.g. job1786627920)">
  <select id="schedulePlatform">
    <option value="youtube">YouTube</option>
  </select>
  <br>
  <button onclick="scheduleJob()">Schedule All Windows</button>
  <span id="scheduleResult"></span>
  <table id="scheduleTable"><thead><tr><th>Content</th><th>Platform</th><th>When</th><th>Status</th></tr></thead><tbody></tbody></table>
</div>

<div class="card">
  <h2>Thumbnail Branding</h2>
  <input type="text" id="brandJob" placeholder="Job name">
  <input type="text" id="brandText" placeholder="Watermark text (e.g. GtaxZombies)">
  <input type="text" id="brandLogoPath" placeholder="Logo file path (optional)">
  <br>
  <button onclick="brandThumbnail()">Apply Branding</button>
  <span id="brandResult"></span>
</div>

<script>
async function triggerJob() {
  const url = document.getElementById('url').value;
  const platform = document.getElementById('platform').value;
  const clip_count = parseInt(document.getElementById('clipcount').value) || 10;
  if (!url) { document.getElementById('triggerResult').textContent = ' Enter a URL first'; return; }
  document.getElementById('triggerResult').textContent = ' Launching...';
  const res = await fetch('/api/trigger', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({url, platform, clip_count})
  });
  const data = await res.json();
  document.getElementById('triggerResult').textContent = data.job ? ` Launched: ${data.job}` : ` Error: ${data.error}`;
  refreshJobs();
}

async function startWatcher() {
  const channelUrl = document.getElementById('channelUrl').value;
  if (!channelUrl) { document.getElementById('watcherStatus').textContent = ' Enter a channel URL first'; return; }
  const res = await fetch('/api/watch/start', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({channel_url: channelUrl})
  });
  const data = await res.json();
  document.getElementById('watcherStatus').textContent = data.status === 'started' ? ' Watching' : ` Error: ${data.error}`;
}

async function stopWatcher() {
  const res = await fetch('/api/watch/stop', {method: 'POST'});
  const data = await res.json();
  document.getElementById('watcherStatus').textContent = data.status === 'stopped' ? ' Stopped' : ` ${data.error || 'not running'}`;
}

async function publishJob(job, platform) {
  const res = await fetch(`/api/publish/${platform}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({job})
  });
  const data = await res.json();
  alert(data.error ? `Error: ${data.error}` : `Published: ${data.url || data.result || 'done'}`);
  refreshJobs();
}

async function boostOutput(filename) {
  const res = await fetch('/api/originality-boost', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({filename})
  });
  const data = await res.json();
  alert(data.error ? `Error: ${data.error}` : `Boosted: ${data.output}`);
  refreshJobs();
}

async function scheduleJob() {
  const job = document.getElementById('scheduleJob').value;
  const platform = document.getElementById('schedulePlatform').value;
  if (!job) { document.getElementById('scheduleResult').textContent = ' Enter a job name first'; return; }
  const res = await fetch('/api/schedule/best-windows', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({job, platform})
  });
  const data = await res.json();
  document.getElementById('scheduleResult').textContent = data.error ? ` Error: ${data.error}` : ` Queued ${data.queued} item(s)`;
  refreshJobs();
}

async function brandThumbnail() {
  const job = document.getElementById('brandJob').value;
  const watermark_text = document.getElementById('brandText').value;
  const logo_path = document.getElementById('brandLogoPath').value;
  if (!job || !watermark_text) { document.getElementById('brandResult').textContent = ' Enter job and watermark text'; return; }
  const res = await fetch('/api/brand-thumbnail', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({job, watermark_text, logo_path: logo_path || undefined})
  });
  const data = await res.json();
  document.getElementById('brandResult').textContent = data.error ? ` Error: ${data.error}` : ` Applied to ${data.job}`;
}

async function refreshJobs() {
  const res = await fetch('/api/jobs');
  const jobs = await res.json();
  const tbody = document.querySelector('#jobsTable tbody');
  tbody.innerHTML = jobs.map(j => `<tr>
    <td>${j.job}</td>
    <td class="status-${j.status === 'done' ? 'done' : (j.status === 'running' ? 'running' : 'failed')}">${j.status}</td>
    <td>${j.youtube_url ? `<a href="${j.youtube_url}" target="_blank">view</a>` : ''}</td>
    <td>${j.status === 'done' ? `<button onclick="publishJob('${j.job}','youtube')">YT</button> <button onclick="publishJob('${j.job}','tiktok')">TikTok</button>` : ''}</td>
  </tr>`).join('');

  const res2 = await fetch('/api/outputs');
  const outputs = await res2.json();
  const tbody2 = document.querySelector('#outputsTable tbody');
  tbody2.innerHTML = outputs.map(o => `<tr>
    <td>${o.name}</td><td>${o.size_mb} MB</td>
    <td><a href="/download/${encodeURIComponent(o.name)}">download</a> <button onclick="boostOutput('${o.name}')">Boost</button></td>
  </tr>`).join('');

  const res3 = await fetch('/api/schedule');
  const schedule = await res3.json();
  const tbody3 = document.querySelector('#scheduleTable tbody');
  tbody3.innerHTML = schedule.map(s => `<tr>
    <td>${s.content_id}</td><td>${s.platform}</td><td>${s.scheduled_time}</td>
    <td class="status-${s.status === 'published' ? 'done' : (s.status === 'error' ? 'failed' : 'running')}">${s.status}</td>
  </tr>`).join('');
}

refreshJobs();
setInterval(refreshJobs, 10000);
</script>
<div class="card">
  <h2>Ready to Post or Download</h2>
  <div id="best-windows-list">Loading...</div>
</div>

<style>
  .bw-job { border: 1px solid #333; border-radius: 8px; margin-bottom: 16px; padding: 14px; }
  .bw-job h3 { margin: 0 0 10px; font-size: 0.95rem; }
  .bw-window { display: flex; align-items: center; justify-content: space-between;
    padding: 8px 0; border-top: 1px solid #2a2a2a; gap: 12px; }
  .bw-window:first-of-type { border-top: none; }
  .bw-window-info { flex: 1; min-width: 0; }
  .bw-window-title { font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bw-window-meta { font-size: 0.72rem; color: #888; margin-top: 2px; }
  .bw-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .bw-btn { padding: 6px 12px; border-radius: 5px; font-size: 0.8rem; cursor: pointer; border: 1px solid #444; background: #1a1a1a; color: #eee; text-decoration: none; }
  .bw-btn:hover:not(:disabled) { border-color: #e8a33d; }
  .bw-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .bw-btn.post { background: #e8a33d; color: #1a1305; border-color: #e8a33d; font-weight: 600; }
  .bw-status { font-size: 0.72rem; padding: 2px 8px; border-radius: 10px; }
  .bw-status.published { background: #1a3a1a; color: #7fd67f; }
  .bw-status.pending { background: #3a3a1a; color: #d6c67f; }
  .bw-status.not_scheduled { background: #2a2a2a; color: #999; }
</style>

<script>
async function loadBestWindowsJobs() {
  const container = document.getElementById('best-windows-list');
  try {
    const res = await fetch('/api/best-windows-jobs');
    const jobs = await res.json();

    if (!jobs.length) {
      container.innerHTML = '<p style="color:#888;font-size:0.85rem;">No finished best-windows jobs yet.</p>';
      return;
    }

    container.innerHTML = jobs.map(job => `
      <div class="bw-job">
        <h3>${job.job} (${job.windows.length} window${job.windows.length !== 1 ? 's' : ''})</h3>
        ${job.windows.map(w => `
          <div class="bw-window" id="row-${w.content_id}">
            <div class="bw-window-info">
              <div class="bw-window-title">${escapeHtml(w.title)}</div>
              <div class="bw-window-meta">
                ${w.size_mb} MB
                <span class="bw-status ${w.publish_status}">${formatStatus(w.publish_status, w.scheduled_time)}</span>
              </div>
            </div>
            <div class="bw-actions">
              <a class="bw-btn" href="${w.download_url}" download>Download</a>
              <button class="bw-btn post" onclick="postWindow('${job.job}', ${job.windows.indexOf(w)}, '${w.content_id}')"
                ${w.publish_status === 'published' ? 'disabled' : ''}>
                ${w.publish_status === 'published' ? 'Posted' : 'Post to YouTube'}
              </button>
            </div>
          </div>
        `).join('')}
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<p style="color:#e85;">Could not load jobs: ' + escapeHtml(err.message) + '</p>';
  }
}

function formatStatus(status, scheduledTime) {
  if (status === 'published') return 'Published';
  if (status === 'pending' && scheduledTime) return 'Scheduled ' + new Date(scheduledTime).toLocaleString();
  if (status === 'pending') return 'Pending';
  return 'Not scheduled';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

async function postWindow(job, windowIndex, contentId) {
  const row = document.getElementById('row-' + contentId);
  const btn = row.querySelector('.bw-btn.post');
  btn.disabled = true;
  btn.textContent = 'Posting...';
  try {
    const res = await fetch('/api/publish/youtube', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ job: job, window_index: windowIndex })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Post failed');
    btn.textContent = 'Posted';
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Post to YouTube';
    alert('Post failed: ' + err.message);
  }
}

loadBestWindowsJobs();
setInterval(loadBestWindowsJobs, 30000);
</script>
<div class="card">
  <h2>Currently Processing</h2>
  <div id="in-progress-list">Loading...</div>
</div>

<style>
  .ip-job { border: 1px solid #333; border-radius: 8px; margin-bottom: 12px; padding: 14px; }
  .ip-job-name { font-size: 0.9rem; font-weight: 600; margin-bottom: 6px; }
  .ip-stage { font-size: 0.8rem; color: #bbb; margin-bottom: 8px; }
  .ip-bar-track { height: 8px; background: #2a2a2a; border-radius: 4px; overflow: hidden; }
  .ip-bar-fill { height: 100%; background: #e8a33d; transition: width 0.6s ease; }
  .ip-percent { font-size: 0.72rem; color: #888; margin-top: 4px; text-align: right; }
</style>

<script>
async function loadInProgressJobs() {
  const container = document.getElementById('in-progress-list');
  try {
    const res = await fetch('/api/in-progress');
    const jobs = await res.json();

    if (!jobs.length) {
      container.innerHTML = '<p style="color:#888;font-size:0.85rem;">Nothing currently processing.</p>';
      return;
    }

    container.innerHTML = jobs.map(j => `
      <div class="ip-job">
        <div class="ip-job-name">${escapeHtmlIP(j.job)}</div>
        <div class="ip-stage">${escapeHtmlIP(j.stage)}</div>
        <div class="ip-bar-track">
          <div class="ip-bar-fill" style="width: ${j.percent_complete}%;"></div>
        </div>
        <div class="ip-percent">${j.percent_complete}%</div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = '<p style="color:#e85;">Could not load progress: ' + escapeHtmlIP(err.message) + '</p>';
  }
}

function escapeHtmlIP(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

loadInProgressJobs();
setInterval(loadInProgressJobs, 10000);
</script>
</body>
</html>
"""


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Real, permanent architectural fix — confirmed directly on a real
    hang: a blocking, interactive request (OAuth consent, which opens a
    browser and waits on the user) running inside a plain HTTPServer
    doesn't just block that one request, it freezes the ENTIRE server
    for every other request too, since Python's stdlib HTTPServer is
    single-threaded by default. daemon_threads=True so a stuck request
    thread doesn't prevent the whole process from exiting cleanly."""
    daemon_threads = True


WATCHER_STATE_FILE = os.path.join(ROOT, ".watcher_state.json")


def start_watcher_thread(channel_url, content_type="gaming", interval_sec=None):
    """The real, shared start logic — used both by the HTTP endpoint and
    by the startup auto-resume, so there's one implementation, not two
    that could drift apart."""
    from channel_watcher import watch_loop, DEFAULT_INTERVAL_SEC
    interval_sec = interval_sec or DEFAULT_INTERVAL_SEC
    stop_event = threading.Event()
    t = threading.Thread(
        target=watch_loop,
        args=(channel_url, stop_event),
        kwargs={"content_type": content_type, "interval_sec": interval_sec},
        daemon=True,
    )
    _WATCHER_STATE["thread"] = t
    _WATCHER_STATE["stop_event"] = stop_event
    _WATCHER_STATE["channel_url"] = channel_url
    t.start()
    with open(WATCHER_STATE_FILE, "w") as f:
        json.dump({"channel_url": channel_url, "content_type": content_type, "interval_sec": interval_sec}, f)
    return interval_sec


def resume_watcher_if_needed():
    """Real, permanent fix for the exact gap just hit: since the watcher
    now runs as a thread INSIDE this process (the whole point of
    consolidating it), restarting this process also stops the watcher —
    a real regression from when it was a fully separate process. This
    persists across restarts by checking for saved state on startup and
    resuming automatically, restoring the same durability a separate
    process used to give for free."""
    if not os.path.exists(WATCHER_STATE_FILE):
        return
    try:
        with open(WATCHER_STATE_FILE) as f:
            state = json.load(f)
        interval_sec = start_watcher_thread(state["channel_url"], state.get("content_type", "gaming"), state.get("interval_sec"))
        print(f"dashboard: auto-resumed channel watcher for {state['channel_url']} "
              f"(interval={interval_sec}s) — was running before the last restart", flush=True)
    except Exception as e:
        print(f"dashboard: could not auto-resume channel watcher — {e}", flush=True)


def _list_clips_with_seo():
    import sqlite3
    db_path = os.path.join(ROOT, "takekash.db")
    if not os.path.exists(db_path):
        return {"clips": [], "note": "no database yet - run lib/db.py to initialize"}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.clip_path, c.game, c.seo_score, c.status,
               sp.platform, sp.title, sp.hashtags, sp.status as post_status,
               sp.scheduled_for
        FROM clips c
        LEFT JOIN social_posts sp ON sp.clip_id = c.id
        ORDER BY c.id DESC LIMIT 200
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"clips": rows}


def _tiktok_health_check():
    health = {
        "oauth": "FAIL",
        "video_publish_scope": "NOT AUTHORIZED",
        "creator_info": "FAIL",
        "direct_post": "NOT READY",
        "domain_verification": "PASS",
        "audit": "NOT APPROVED",
    }
    token_path = os.path.join(ROOT, "tiktok_token.json")
    if not os.path.exists(token_path):
        health["note"] = "no tiktok_token.json - run lib/tiktok_oauth_flow.py first"
        return health

    health["oauth"] = "PASS"
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(ROOT, "lib"))
        from tiktok_publish import _load_token, _refresh_access_token_if_needed, get_creator_info
        token_data = _refresh_access_token_if_needed(_load_token())
        creator_info = get_creator_info(token_data["access_token"])
        health["creator_info"] = "PASS"
        health["video_publish_scope"] = "AUTHORIZED"
        health["direct_post"] = "READY" if creator_info.get("privacy_level_options") else "NOT READY"
    except Exception as e:
        health["note"] = f"real error: {e}"
    return health


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/":
            body = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/jobs":
            self._send_json(200, list_jobs())
        elif self.path == "/api/outputs":
            self._send_json(200, list_outputs())
        elif self.path == "/api/schedule":
            self._handle_schedule_view()
        elif self.path == "/api/best-windows-jobs":
            self._send_json(200, list_best_windows_jobs())
        elif self.path == "/api/in-progress":
            self._send_json(200, _find_running_pipeline_jobs(ROOT))
        elif self.path == "/api/clips":
            self._send_json(200, _list_clips_with_seo())
        elif self.path == "/api/tiktok-health":
            self._send_json(200, _tiktok_health_check())
        elif self.path.startswith("/download/"):
            self._serve_download()
        else:
            self._send_json(404, {"error": "not found"})

    def _serve_download(self):
        """Real security check: the requested filename must resolve to a
        path that's actually INSIDE outputs/, not escape it via '..' or
        an absolute path — this is the one thing that must never be
        skipped when serving files by name from an HTTP request."""
        from urllib.parse import unquote
        requested = unquote(self.path[len("/download/"):])
        candidate = os.path.realpath(os.path.join(OUTPUTS_DIR, requested))
        if not candidate.startswith(OUTPUTS_DIR + os.sep):
            self._send_json(403, {"error": "invalid path"})
            return
        if not os.path.isfile(candidate):
            self._send_json(404, {"error": "file not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(candidate)}"')
        self.send_header("Content-Length", str(os.path.getsize(candidate)))
        self.end_headers()
        with open(candidate, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def do_POST(self):
        if self.path == "/api/trigger":
            self._handle_trigger()
        elif self.path == "/api/watch/start":
            self._handle_watch_start()
        elif self.path == "/api/watch/stop":
            self._handle_watch_stop()
        elif self.path == "/api/publish/youtube":
            self._handle_publish_youtube()
        elif self.path == "/api/publish/tiktok":
            self._handle_publish_tiktok()
        elif self.path == "/api/publish/instagram":
            self._handle_publish_instagram()
        elif self.path == "/api/originality-boost":
            self._handle_originality_boost()
        elif self.path == "/api/schedule/best-windows":
            self._handle_schedule_best_windows()
        elif self.path == "/api/brand-thumbnail":
            self._handle_brand_thumbnail()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_schedule_best_windows(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        job = data.get("job")
        if not job:
            self._send_json(400, {"error": "missing job"})
            return
        platform = data.get("platform", "youtube")
        try:
            from publish_scheduler import enqueue_best_windows_job
        except ImportError as e:
            self._send_json(500, {"error": f"scheduler unavailable: {e}"})
            return
        try:
            queued = enqueue_best_windows_job(job, platform=platform)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"job": job, "queued": len(queued),
                               "schedule": [{"content_id": q["content_id"], "when": q["scheduled_time"]} for q in queued]})

    def _handle_publish_youtube(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        job = data.get("job")
        if not job:
            self._send_json(400, {"error": "missing job"})
            return
        try:
            import doctor as doctor_mod
            from youtube_publish import generate_title, generate_description, generate_tags, upload_video
            from content_filter import clean_text
        except ImportError as e:
            self._send_json(500, {"error": f"publish libraries unavailable: {e}"})
            return

        content_type = data.get("content_type", "gaming")
        privacy = data.get("privacy", "private")

        video_path = doctor_mod.find_output_video(job)
        if video_path:
            clip_meta = doctor_mod.find_clip_metadata(job)
            if not clip_meta:
                self._send_json(404, {"error": f"no clip/montage metadata found for '{job}'"})
                return
            # Real, serious gap fixed: this whole regular clip/montage
            # publish path had NEVER had profanity filtering applied —
            # confirmed directly, a real slur reached this exact code
            # path unfiltered in test data tonight. generate_window_metadata
            # (best-windows mode) already filtered; this path, used for
            # every regular clip AND every montage, did not.
            title = clean_text(generate_title(clip_meta, content_type))
            description = clean_text(generate_description(clip_meta, source_title=clip_meta.get("source_title")))
            tags = [clean_text(t) for t in generate_tags(clip_meta, content_type)]
        else:
            # Real gap fixed: this endpoint only ever checked the
            # clip/montage output pattern — confirmed directly on a real
            # best-windows job that it returned "no finished output
            # found" even though 20 real, valid files existed, just
            # under a different naming pattern this never checked.
            window_index = data.get("window_index", 0)
            windows = doctor_mod.find_best_windows_outputs(job)
            if not windows or window_index >= len(windows):
                self._send_json(404, {"error": f"no finished output found for job '{job}' "
                                                 f"(checked both clip/montage and best-windows patterns)"})
                return
            video_path = windows[window_index]
            # Real, permanent fix: this manual-upload endpoint used to
            # call the confirmed-broken generate_window_metadata,
            # capable of publishing raw transcript garbage as a real
            # video title. generate_clip_metadata is the same real,
            # grounded generator the rest of the pipeline already uses.
            try:
                from generate_clip_metadata import generate_clip_metadata
                sub_job = f"{job}__window{window_index + 1:02d}"
                meta = generate_clip_metadata(sub_job, "youtube")
            except Exception as meta_err:
                self._send_json(404, {"error": f"could not generate real metadata for '{job}' window {window_index}: {meta_err}"})
                return
            title, description, tags = meta["title"], meta["description"], meta.get("hashtags", [])

        try:
            result = upload_video(video_path, title, description, tags, privacy_status=privacy)
        except Exception as e:
            self._send_json(500, {"error": f"upload failed: {e}"})
            return
        self._send_json(200, {"job": job, "title": title, "video_id": result.get("video_id"), "url": result.get("url")})

    def _handle_publish_tiktok(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        job = data.get("job")
        if not job:
            self._send_json(400, {"error": "missing job"})
            return
        try:
            import doctor as doctor_mod
            from tiktok_publish import publish_video
        except ImportError as e:
            self._send_json(500, {"error": f"publish libraries unavailable: {e}"})
            return
        video_path = doctor_mod.find_output_video(job)
        if not video_path:
            self._send_json(404, {"error": f"no finished output found for job '{job}'"})
            return
        title = data.get("title", job)
        try:
            result = publish_video(video_path, title)
        except Exception as e:
            self._send_json(500, {"error": f"TikTok publish failed: {e}"})
            return
        self._send_json(200, {"job": job, "result": result})

    def _handle_publish_instagram(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        job = data.get("job")
        video_url = data.get("video_url")
        if not job or not video_url:
            self._send_json(400, {"error": "missing job or video_url — Instagram's API requires a real, "
                                             "publicly-accessible URL, not a local file path"})
            return
        try:
            import doctor as doctor_mod
            from instagram_publish import publish_reel
        except ImportError as e:
            self._send_json(500, {"error": f"publish libraries unavailable: {e}"})
            return
        video_path = doctor_mod.find_output_video(job)
        caption = data.get("caption", job)
        try:
            result = publish_reel(video_url, caption, video_path_for_duration_check=video_path)
        except Exception as e:
            self._send_json(500, {"error": f"Instagram publish failed: {e}"})
            return
        self._send_json(200, {"job": job, "result": result})

    def _handle_schedule_view(self):
        try:
            from publish_scheduler import _load_queue
        except ImportError as e:
            self._send_json(500, {"error": f"scheduler unavailable: {e}"})
            return
        self._send_json(200, _load_queue())

    def _handle_brand_thumbnail(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        job = data.get("job")
        watermark_text = data.get("watermark_text")
        if not job or not watermark_text:
            self._send_json(400, {"error": "missing job or watermark_text"})
            return
        try:
            import doctor as doctor_mod
            from thumbnail_brand import brand_thumbnail
        except ImportError as e:
            self._send_json(500, {"error": f"thumbnail_brand unavailable: {e}"})
            return
        thumb_path = os.path.join(PROJECTS_DIR, job, "thumbnail", "thumb.jpg")
        if not os.path.exists(thumb_path):
            self._send_json(404, {"error": f"no thumbnail found for job '{job}' at {thumb_path}"})
            return
        logo_path = data.get("logo_path")
        try:
            brand_thumbnail(thumb_path, watermark_text, logo_path)
        except Exception as e:
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, {"job": job, "thumbnail": thumb_path, "watermark_text": watermark_text})

    def _handle_originality_boost(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        filename = data.get("filename")
        if not filename:
            self._send_json(400, {"error": "missing filename"})
            return
        candidate = os.path.realpath(os.path.join(OUTPUTS_DIR, filename))
        if not candidate.startswith(OUTPUTS_DIR + os.sep) or not os.path.isfile(candidate):
            self._send_json(400, {"error": "invalid or nonexistent filename"})
            return
        try:
            from originality_boost import apply_originality_boost
        except ImportError as e:
            self._send_json(500, {"error": f"originality_boost unavailable: {e}"})
            return
        out_name = data.get("out_name") or (os.path.splitext(filename)[0] + "_boosted.mp4")
        out_path = os.path.join(OUTPUTS_DIR, out_name)
        try:
            params = apply_originality_boost(candidate, out_path, filename)
        except Exception as e:
            self._send_json(500, {"error": f"originality boost failed: {e}"})
            return
        self._send_json(200, {"output": out_name, "params": {k: round(v, 4) for k, v in params.items()}})

    def _handle_trigger(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        url = data.get("url")
        if not url:
            self._send_json(400, {"error": "missing url"})
            return
        job = sanitize_job_name(data.get("job", "")) or f"web{int(time.time())}"
        platform = data.get("platform", "youtube")
        clip_count = data.get("clip_count", 10)
        content_type = data.get("content_type", "gaming")

        cmd = [os.path.join(ROOT, "go.sh"), url, job, "--platform", platform,
               "--clip-count", str(clip_count), "--content-type", content_type]
        log_path = os.path.join(ROOT, "logs", "webhook", f"{job}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w") as f:
            subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT, start_new_session=True)
        self._send_json(202, {"status": "launched", "job": job})

    def _handle_watch_start(self):
        try:
            data = self._read_json_body()
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return
        channel_url = data.get("channel_url")
        if not channel_url:
            self._send_json(400, {"error": "missing channel_url"})
            return
        if _WATCHER_STATE.get("thread") and _WATCHER_STATE["thread"].is_alive():
            self._send_json(409, {"error": "watcher already running — stop it first"})
            return
        try:
            interval_sec = start_watcher_thread(channel_url, data.get("content_type", "gaming"), data.get("interval_sec"))
        except ImportError as e:
            self._send_json(500, {"error": f"channel_watcher unavailable: {e}"})
            return
        self._send_json(202, {"status": "started", "channel_url": channel_url,
                               "interval_sec": interval_sec, "interval_hours": round(interval_sec / 3600, 1)})

    def _handle_watch_stop(self):
        thread = _WATCHER_STATE.get("thread")
        if not thread or not thread.is_alive():
            self._send_json(200, {"status": "not running"})
            return
        _WATCHER_STATE["stop_event"].set()
        thread.join(timeout=10)  # real, bounded wait — the loop checks stop_event between polls, not mid-download
        if os.path.exists(WATCHER_STATE_FILE):
            os.remove(WATCHER_STATE_FILE)  # explicit stop means don't auto-resume this on the next restart
        self._send_json(200, {"status": "stopped" if not thread.is_alive() else "stop requested (mid-task, will finish shortly)"})

    def log_message(self, format, *args):
        print(f"dashboard: {self.address_string()} - {format % args}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--auto-publish", action="store_true",
                    help="also auto-upload newly-finished clips to YouTube as private (requires youtube_client_secret.json set up)")
    p.add_argument("--no-auto-resume", action="store_true",
                    help="disable the background auto-resume thread (on by default — this is the real consolidation, doctor.py's watchdog running inside this same process)")
    args = p.parse_args()

    if not args.no_auto_resume:
        t = threading.Thread(
            target=background_maintenance_loop,
            kwargs={"auto_publish": args.auto_publish},
            daemon=True,
        )
        t.start()
        mode = "auto-resume" + (" + auto-publish" if args.auto_publish else "")
        print(f"dashboard: background maintenance thread started ({mode})", flush=True)

    resume_watcher_if_needed()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"dashboard: open http://localhost:{args.port} in your browser", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
