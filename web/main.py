import json
import os
import re
import subprocess
import sys
import uuid

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects")
OUTPUTS = os.path.join(ROOT, "outputs")
FORMATS_DIR = os.path.join(ROOT, "formats")
JOB_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_UPLOAD_BYTES = int(os.environ.get("PIPELINE_MAX_UPLOAD_BYTES", 200 * 1024 * 1024 * 1024))  # 200GB default — livestream VODs run big
ALLOWED_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}

app = FastAPI(title="autoclip-pipeline")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "web", "static")), name="static")


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def _jobstate(*args):
    return _run([sys.executable, os.path.join(ROOT, "lib", "jobstate.py"), *args])


URL_RE = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.I)  # any well-formed http(s) URL, not YouTube-specific


def _fetch_url(job: str, url: str):
    """Downloads a URL into projects/<job>/raw/source.mp4 via yt-dlp.
    Returns (ok, message)."""
    r = _run([sys.executable, os.path.join(ROOT, "lib", "fetch_url.py"), job, url])
    if r.returncode != 0:
        return False, (r.stdout.strip() or r.stderr[-2000:])
    return True, r.stdout.strip()


def _valid_job(job: str):
    if not JOB_ID_RE.match(job):
        raise HTTPException(400, "invalid job id")


def _valid_format(fmt: str):
    # exact match against a known format file already prevents path
    # traversal in practice, but reject anything with a path separator or
    # ".." outright too — belt and suspenders, not just an existence check
    if "/" in fmt or "\\" in fmt or ".." in fmt:
        raise HTTPException(400, f"invalid format: {fmt}")
    if not os.path.exists(os.path.join(FORMATS_DIR, f"{fmt}.json")):
        raise HTTPException(400, f"unknown format: {fmt}")


def _job_status(job: str):
    r = _jobstate("path", job)
    path = r.stdout.strip()
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _background_run(job: str, fmt: str, skip_music: bool, content_type: str = ""):
    lock_path = os.path.join(PROJECTS, job, ".lock")
    if os.path.exists(lock_path):
        return
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    open(lock_path, "w").close()
    try:
        args = [os.path.join(ROOT, "run_pipeline.sh"), job, fmt]
        if skip_music:
            args.append("--skip-music")
        if content_type:
            args += ["--content-type", content_type]
        result = _run(args)
        if result.returncode != 0:
            _jobstate("set", job, "error",
                      json.dumps(result.stderr[-2000:] or result.stdout[-2000:]))
        else:
            _jobstate("set", job, "error", "null")
    finally:
        os.remove(lock_path)


def _background_clip_run(job: str, fmt: str, clip_length: int, clip_count: int,
                          skip_music: bool, content_type: str = ""):
    lock_path = os.path.join(PROJECTS, job, ".lock")
    if os.path.exists(lock_path):
        return
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    open(lock_path, "w").close()
    try:
        args = [os.path.join(ROOT, "clip_pipeline.sh"), job, fmt,
                "--clip-length", str(clip_length), "--clip-count", str(clip_count)]
        if skip_music:
            args.append("--skip-music")
        if content_type:
            args += ["--content-type", content_type]
        result = _run(args)
        if result.returncode != 0:
            _jobstate("set", job, "error",
                      json.dumps(result.stderr[-2000:] or result.stdout[-2000:]))
        else:
            _jobstate("set", job, "error", "null")
    finally:
        os.remove(lock_path)


@app.get("/")
def index():
    return FileResponse(os.path.join(ROOT, "web", "static", "index.html"))


@app.get("/api/formats")
def list_formats():
    out = []
    for f in sorted(os.listdir(FORMATS_DIR)):
        if f.endswith(".json"):
            out.append(f[:-5])
    return out


@app.get("/api/jobs")
def list_jobs():
    if not os.path.isdir(PROJECTS):
        return []
    jobs = []
    for name in sorted(os.listdir(PROJECTS)):
        status = _job_status(name)
        if status:
            jobs.append(status)
    return jobs


CONTENT_TYPES = {"podcast", "gaming", "irl"}


@app.get("/api/content-types")
def list_content_types():
    return sorted(CONTENT_TYPES)


def _background_run_from_url(job: str, url: str, fmt: str, skip_music: bool, content_type: str = ""):
    lock_path = os.path.join(PROJECTS, job, ".lock")
    if os.path.exists(lock_path):
        return
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    open(lock_path, "w").close()
    try:
        if not os.path.exists(os.path.join(PROJECTS, job, "job.json")):
            _jobstate("init", job, fmt, "")
        if content_type:
            _jobstate("set", job, "content_type", json.dumps(content_type))

        ok, msg = _fetch_url(job, url)
        if not ok:
            _jobstate("set", job, "error", json.dumps(f"download failed: {msg}"))
            return
        raw_path = os.path.join(PROJECTS, job, "raw", "source.mp4")
        _jobstate("set", job, "raw", json.dumps(raw_path))

        args = [os.path.join(ROOT, "run_pipeline.sh"), job, fmt]
        if skip_music:
            args.append("--skip-music")
        if content_type:
            args += ["--content-type", content_type]
        result = _run(args)
        if result.returncode != 0:
            _jobstate("set", job, "error",
                      json.dumps(result.stderr[-2000:] or result.stdout[-2000:]))
        else:
            _jobstate("set", job, "error", "null")
    finally:
        os.remove(lock_path)


def _background_clip_run_from_url(job: str, url: str, fmt: str, clip_length: int, clip_count: int,
                                    skip_music: bool, content_type: str = ""):
    lock_path = os.path.join(PROJECTS, job, ".lock")
    if os.path.exists(lock_path):
        return
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    open(lock_path, "w").close()
    try:
        if not os.path.exists(os.path.join(PROJECTS, job, "job.json")):
            _jobstate("init", job, fmt, "")

        ok, msg = _fetch_url(job, url)
        if not ok:
            _jobstate("set", job, "error", json.dumps(f"download failed: {msg}"))
            return
        raw_path = os.path.join(PROJECTS, job, "raw", "source.mp4")
        _jobstate("set", job, "raw", json.dumps(raw_path))

        args = [os.path.join(ROOT, "clip_pipeline.sh"), job, fmt,
                "--clip-length", str(clip_length), "--clip-count", str(clip_count)]
        if skip_music:
            args.append("--skip-music")
        if content_type:
            args += ["--content-type", content_type]
        result = _run(args)
        if result.returncode != 0:
            _jobstate("set", job, "error",
                      json.dumps(result.stderr[-2000:] or result.stdout[-2000:]))
        else:
            _jobstate("set", job, "error", "null")
    finally:
        os.remove(lock_path)


@app.post("/api/jobs-url")
async def create_job_from_url(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    format: str = Form(...),
    job: str = Form(None),
    skip_music: bool = Form(False),
    content_type: str = Form(""),
):
    _valid_format(format)
    if not URL_RE.match(url):
        raise HTTPException(400, "invalid url")
    job = job or uuid.uuid4().hex[:12]
    _valid_job(job)
    if content_type and content_type not in CONTENT_TYPES:
        raise HTTPException(400, f"unknown content_type: {content_type}")

    existing = _job_status(job)
    if existing and os.path.exists(os.path.join(PROJECTS, job, ".lock")):
        raise HTTPException(409, f"job '{job}' is already running")

    background_tasks.add_task(_background_run_from_url, job, url, format, skip_music, content_type)
    return {"job": job, "format": format, "status": "downloading"}


@app.post("/api/clip-jobs-url")
async def create_clip_job_from_url(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    format: str = Form(...),
    job: str = Form(None),
    clip_length: int = Form(60),
    clip_count: int = Form(3),
    skip_music: bool = Form(False),
    content_type: str = Form(""),
):
    _valid_format(format)
    if not URL_RE.match(url):
        raise HTTPException(400, "invalid url")
    job = job or uuid.uuid4().hex[:12]
    _valid_job(job)
    if content_type and content_type not in CONTENT_TYPES:
        raise HTTPException(400, f"unknown content_type: {content_type}")
    if not (5 <= clip_length <= 600):
        raise HTTPException(400, "clip_length must be between 5 and 600 seconds")
    if not (1 <= clip_count <= 20):
        raise HTTPException(400, "clip_count must be between 1 and 20")

    existing = _job_status(job)
    if existing and os.path.exists(os.path.join(PROJECTS, job, ".lock")):
        raise HTTPException(409, f"job '{job}' is already running")

    background_tasks.add_task(
        _background_clip_run_from_url, job, url, format, clip_length, clip_count,
        skip_music, content_type,
    )
    return {"job": job, "format": format, "status": "downloading", "mode": "clip"}


@app.post("/api/jobs")
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format: str = Form(...),
    job: str = Form(None),
    skip_music: bool = Form(False),
    content_type: str = Form(""),
):
    _valid_format(format)
    job = job or uuid.uuid4().hex[:12]
    _valid_job(job)
    if content_type and content_type not in CONTENT_TYPES:
        raise HTTPException(400, f"unknown content_type: {content_type}")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"unsupported file type: {ext or '(none)'}")

    existing = _job_status(job)
    if existing and os.path.exists(os.path.join(PROJECTS, job, ".lock")):
        raise HTTPException(409, f"job '{job}' is already running")

    raw_dir = os.path.join(PROJECTS, job, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    # never join a client-supplied filename into a path directly — a
    # filename like "../../../evil.mp4" would escape raw_dir. Only the
    # extension (already validated against ALLOWED_EXTS) survives.
    dest = os.path.join(raw_dir, f"source{ext}")
    written = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(dest)
                raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // (1024**3)}GB)")
            f.write(chunk)

    if not os.path.exists(os.path.join(PROJECTS, job, "job.json")):
        _jobstate("init", job, format, dest)
    if content_type:
        _jobstate("set", job, "content_type", json.dumps(content_type))

    background_tasks.add_task(_background_run, job, format, skip_music, content_type)
    return {"job": job, "format": format, "status": "started"}


@app.post("/api/clip-jobs")
async def create_clip_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    format: str = Form(...),
    job: str = Form(None),
    clip_length: int = Form(60),
    clip_count: int = Form(3),
    skip_music: bool = Form(False),
    content_type: str = Form(""),
):
    _valid_format(format)
    job = job or uuid.uuid4().hex[:12]
    _valid_job(job)
    if content_type and content_type not in CONTENT_TYPES:
        raise HTTPException(400, f"unknown content_type: {content_type}")
    if not (5 <= clip_length <= 600):
        raise HTTPException(400, "clip_length must be between 5 and 600 seconds")
    if not (1 <= clip_count <= 20):
        raise HTTPException(400, "clip_count must be between 1 and 20")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"unsupported file type: {ext or '(none)'}")

    existing = _job_status(job)
    if existing and os.path.exists(os.path.join(PROJECTS, job, ".lock")):
        raise HTTPException(409, f"job '{job}' is already running")

    raw_dir = os.path.join(PROJECTS, job, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    dest = os.path.join(raw_dir, f"source{ext}")
    written = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                f.close()
                os.remove(dest)
                raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // (1024**3)}GB)")
            f.write(chunk)

    background_tasks.add_task(
        _background_clip_run, job, format, clip_length, clip_count, skip_music, content_type
    )
    return {"job": job, "format": format, "status": "started", "mode": "clip"}


@app.get("/api/jobs/{job}")
def job_status(job: str):
    _valid_job(job)
    status = _job_status(job)
    if status is None:
        raise HTTPException(404, "job not found")
    return status


@app.post("/api/jobs/{job}/approve")
def approve(job: str, background_tasks: BackgroundTasks, skip_music: bool = Form(False)):
    _valid_job(job)
    status = _job_status(job)
    if status is None:
        raise HTTPException(404, "job not found")
    r = _jobstate("mark", job, "second_pass", "done")
    if r.returncode != 0:
        raise HTTPException(500, r.stderr)
    _jobstate("set", job, "error", "null")
    content_type = status.get("content_type", "") or ""
    background_tasks.add_task(_background_run, job, status["format"], skip_music, content_type)
    return {"job": job, "status": "resumed"}


@app.get("/api/jobs/{job}/output")
def job_output(job: str):
    _valid_job(job)
    path = os.path.join(OUTPUTS, f"{job}.final.mp4")
    if not os.path.exists(path):
        raise HTTPException(404, "not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"{job}.final.mp4")


@app.get("/api/jobs/{job}/thumbnail")
def job_thumbnail(job: str):
    _valid_job(job)
    path = os.path.join(PROJECTS, job, "thumbnail", "thumb.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "not ready")
    return FileResponse(path, media_type="image/jpeg")


def _clip_outputs(parent_job: str):
    """Finds outputs/<parent_job>__clip*.final.mp4 for a clip_pipeline run,
    or [outputs/<parent_job>.final.mp4] for a regular single-output job."""
    single = os.path.join(OUTPUTS, f"{parent_job}.final.mp4")
    if os.path.exists(single):
        return [single]
    if not os.path.isdir(OUTPUTS):
        return []
    prefix = f"{parent_job}__"
    return sorted(
        os.path.join(OUTPUTS, f)
        for f in os.listdir(OUTPUTS)
        if f.startswith(prefix) and f.endswith(".final.mp4")
    )


@app.get("/api/jobs/{job}/download-all")
def download_all(job: str):
    _valid_job(job)
    files = _clip_outputs(job)
    if not files:
        raise HTTPException(404, "no finished outputs for this job")

    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, f in enumerate(files, start=1):
            # numeric-labeled so they sort/drag-drop in order regardless of
            # the original job-id-based filename
            zf.write(f, arcname=f"{i:02d}.mp4")
    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{job}_clips.zip"'},
    )


@app.post("/api/jobs/{job}/publish")
def publish_job(
    job: str,
    background_tasks: BackgroundTasks,
    platform: str = Form("youtube"),
    title: str = Form(None),
    description: str = Form(""),
    privacy: str = Form("private"),
    tags: str = Form(""),
):
    _valid_job(job)
    if platform != "youtube":
        raise HTTPException(400, f"'{platform}' publishing isn't wired up yet — only 'youtube' is supported")

    files = _clip_outputs(job)
    if not files:
        raise HTTPException(404, "no finished output to publish")

    def _do_publish():
        for f in files:
            r = _run([
                sys.executable, os.path.join(ROOT, "skills", "publish", "youtube_upload.py"),
                job, f, "--title", title or os.path.splitext(os.path.basename(f))[0],
                "--description", description, "--privacy", privacy, "--tags", tags,
            ])
            out = r.stdout.strip()
            try:
                result = json.loads(out)
            except json.JSONDecodeError:
                result = {"error": r.stderr[-500:] or out}
            key = f"publish.{os.path.basename(f).replace('.', '_')}"
            _jobstate("set", job, key, json.dumps(result))

    background_tasks.add_task(_do_publish)
    return {"job": job, "status": "publishing", "files": [os.path.basename(f) for f in files]}


@app.exception_handler(HTTPException)
def http_exc_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
