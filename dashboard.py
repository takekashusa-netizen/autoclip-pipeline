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


def background_maintenance_loop(interval_sec=120, resume_interval_sec=600, publish_interval_sec=300,
                                 metadata_interval_sec=60, schedule_interval_sec=300,
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
        from publish_scheduler import process_due_items
    except ImportError as e:
        process_due_items = None
        print(f"dashboard: publish scheduler unavailable — {e}", flush=True)

    last_resume = 0.0
    last_publish = 0.0
    last_metadata = 0.0
    last_schedule = 0.0
    while True:
        try:
            if time.time() - last_resume >= resume_interval_sec:
                doctor_mod.auto_resume(auto_approve=True)
                last_resume = time.time()
            if generate_metadata_for_all_finished_jobs and time.time() - last_metadata >= metadata_interval_sec:
                generated = generate_metadata_for_all_finished_jobs(content_type=content_type)
                if generated:
                    print(f"dashboard: generated metadata for {len(generated)} newly-finished job(s): {generated}", flush=True)
                last_metadata = time.time()
            if process_due_items and time.time() - last_schedule >= schedule_interval_sec:
                published = process_due_items()
                if published:
                    print(f"dashboard: processed {len(published)} due schedule item(s)", flush=True)
                last_schedule = time.time()
            if auto_publish and time.time() - last_publish >= publish_interval_sec:
                doctor_mod.publish_pending_jobs()
                last_publish = time.time()
        except Exception as e:
            print(f"dashboard: background maintenance error (continuing): {e}", flush=True)
        time.sleep(interval_sec)


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
            title = generate_title(clip_meta, content_type)
            description = generate_description(clip_meta, source_title=clip_meta.get("source_title"))
            tags = generate_tags(clip_meta, content_type)
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
            meta = doctor_mod.generate_window_metadata(job, window_index)
            if not meta:
                self._send_json(404, {"error": f"no window metadata available for '{job}' window {window_index}"})
                return
            title, description, tags = meta["title"], meta["description"], []

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
