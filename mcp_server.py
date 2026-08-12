#!/usr/bin/env python3
"""
mcp_server.py

A minimal MCP (Model Context Protocol) server exposing this pipeline as
tools any MCP client — Claude Desktop, Cursor, etc. — can call directly by
name, same idea as OpusClip's MCP integration: "clip this YouTube link and
give me the top 5 highlights" from a chat window, no CLI/curl/web-UI
needed.

No external SDK dependency — implements the JSON-RPC 2.0 / stdio transport
directly, since the official `mcp` package isn't guaranteed to be
installed. Newline-delimited JSON-RPC 2.0 messages over stdin/stdout, per
the MCP spec's stdio transport.

Run: python3 mcp_server.py
Configure in Claude Desktop's claude_desktop_config.json:
  {"mcpServers": {"autoclip-pipeline": {"command": "python3",
    "args": ["/absolute/path/to/mcp_server.py"]}}}
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def _jobstate(*args):
    return _run([sys.executable, os.path.join(ROOT, "lib", "jobstate.py"), *args])


def _job_status_dict(job):
    r = _jobstate("path", job)
    path = r.stdout.strip()
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


# ---- tool implementations ---------------------------------------------

def tool_submit_clip_job(args):
    url = args["url"]
    fmt = args.get("format", "short-tiktok-raw")
    clip_length = args.get("clip_length", 60)
    clip_count = args.get("clip_count", 5)
    content_type = args.get("content_type", "")
    job = args.get("job") or __import__("uuid").uuid4().hex[:12]

    fetch = _run([sys.executable, os.path.join(ROOT, "lib", "fetch_url.py"), job, url])
    if fetch.returncode != 0:
        return {"error": f"download failed: {fetch.stdout.strip() or fetch.stderr[-500:]}"}

    cmd = [os.path.join(ROOT, "clip_pipeline.sh"), job, fmt,
           "--clip-length", str(clip_length), "--clip-count", str(clip_count)]
    if content_type:
        cmd += ["--content-type", content_type]
    # runs detached — clip jobs take a long time, MCP tool calls shouldn't block for hours
    subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"job": job, "status": "started", "note": "runs in background — use get_job_status to check progress"}


def tool_get_job_status(args):
    job = args["job"]
    status = _job_status_dict(job)
    if status is None:
        return {"error": f"no job found with id '{job}'"}
    return status


def tool_list_jobs(args):
    projects_dir = os.path.join(ROOT, "projects")
    if not os.path.isdir(projects_dir):
        return {"jobs": []}
    jobs = []
    for name in sorted(os.listdir(projects_dir)):
        status = _job_status_dict(name)
        if status:
            jobs.append({
                "job": name, "format": status.get("format"),
                "steps": {k: v.get("status") for k, v in status.get("steps", {}).items()},
                "error": status.get("error"),
            })
    return {"jobs": jobs}


def tool_approve_job(args):
    job = args["job"]
    fmt = args.get("format")
    if not fmt:
        status = _job_status_dict(job)
        if status is None:
            return {"error": f"no job found with id '{job}'"}
        fmt = status["format"]
    r = _jobstate("mark", job, "second_pass", "done")
    if r.returncode != 0:
        return {"error": r.stderr}
    subprocess.Popen([os.path.join(ROOT, "run_pipeline.sh"), job, fmt],
                      cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"job": job, "status": "resumed"}


def tool_list_finished_clips(args):
    job = args.get("job")
    outputs_dir = os.path.join(ROOT, "outputs")
    if not os.path.isdir(outputs_dir):
        return {"clips": []}
    clips = []
    for f in sorted(os.listdir(outputs_dir)):
        if not f.endswith(".final.mp4"):
            continue
        if job and not f.startswith(job):
            continue
        clips.append(os.path.join(outputs_dir, f))
    return {"clips": clips}


def tool_publish_to_youtube(args):
    """Merges doctor.py's auto-publish logic into the MCP server — same
    underlying functions, callable on-demand from Claude Desktop instead
    of only on doctor's watch cycle. Stays private by default, same
    safety reasoning as doctor.py: a human should review before making
    anything public."""
    job = args["job"]
    content_type = args.get("content_type", "gaming")
    privacy = args.get("privacy", "private")

    sys.path.insert(0, os.path.join(ROOT, "lib"))
    try:
        import doctor as doctor_mod
        from youtube_publish import generate_title, generate_description, generate_tags, upload_video
    except ImportError as e:
        return {"error": f"publish libraries unavailable: {e}"}

    video_path = doctor_mod.find_output_video(job)
    if not video_path:
        return {"error": f"no finished output found for job '{job}' — check it's actually done first"}
    clip_meta = doctor_mod.find_clip_metadata(job)
    if not clip_meta:
        return {"error": f"no clip/montage metadata found for '{job}' — not a recognized clip or montage subjob"}

    title = generate_title(clip_meta, content_type)
    description = generate_description(clip_meta, source_title=clip_meta.get("source_title"))
    tags = generate_tags(clip_meta, content_type)

    try:
        result = upload_video(video_path, title, description, tags, privacy_status=privacy)
    except Exception as e:
        return {"error": f"upload failed: {e}"}

    job_json_path = os.path.join(ROOT, "projects", job, "job.json")
    if os.path.exists(job_json_path):
        with open(job_json_path) as f:
            job_data = json.load(f)
        job_data["youtube_video_id"] = result.get("video_id")
        job_data["youtube_url"] = result.get("url")
        with open(job_json_path, "w") as f:
            json.dump(job_data, f, indent=2)

    return {"job": job, "title": title, "video_id": result.get("video_id"), "url": result.get("url")}


def _script_for_job(job):
    path = os.path.join(ROOT, "projects", job, "rough-cut", "script.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def tool_search_video_content(args):
    """Real, honest scope: keyword/substring search across the actual
    transcript, not semantic/AI understanding (that would need a live
    embeddings or LLM call this environment doesn't have configured).
    Case-insensitive substring match against each segment's text,
    returns matching segments with real timestamps."""
    job = args["job"]
    query = args["query"].lower()
    script = _script_for_job(job)
    if script is None:
        return {"error": f"no transcript found for job '{job}' — check it's finished rough-cut"}
    matches = [
        {"start": s["start"], "end": s["end"], "text": s["text"]}
        for s in script.get("kept_segments", [])
        if query in s["text"].lower()
    ]
    return {"job": job, "query": args["query"], "match_count": len(matches), "matches": matches}


def tool_get_key_moments(args):
    """Real key-moment extraction using what this pipeline actually
    detects: transcript hooks/highlights (beat_planner's classify),
    visual motion spikes, and audio gunfire/impact transients — the
    same three signals clip selection uses, exposed directly instead
    of only through the clipping pipeline."""
    job = args["job"]
    script = _script_for_job(job)
    if script is None:
        return {"error": f"no transcript found for job '{job}' — check it's finished rough-cut"}

    sys.path.insert(0, os.path.join(ROOT, "skills", "graphics-plan"))
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from beat_planner import classify  # noqa: E402

    moments = []
    for i, seg in enumerate(script.get("kept_segments", [])):
        tags = classify(seg, i, is_first=(i == 0))
        if tags:
            moments.append({"start": seg["start"], "end": seg["end"], "text": seg["text"], "tags": tags})

    visual_path = os.path.join(ROOT, "projects", job, "rough-cut", "visual-analysis.json")
    if os.path.exists(visual_path):
        try:
            from visual_analysis import motion_beats
            with open(visual_path) as f:
                va = json.load(f)
            if "samples" in va:
                for beat in motion_beats(va):
                    moments.append({"start": beat["start"], "end": beat["end"], "text": beat["text"], "tags": beat["tags"]})
        except Exception:
            pass

    audio_path = os.path.join(ROOT, "projects", job, "rough-cut", "audio-analysis.json")
    if os.path.exists(audio_path):
        try:
            from audio_analysis import transient_beats
            with open(audio_path) as f:
                aa = json.load(f)
            if "transients" in aa:
                for beat in transient_beats(aa):
                    moments.append({"start": beat["start"], "end": beat["end"], "text": beat["text"], "tags": beat["tags"]})
        except Exception:
            pass

    moments.sort(key=lambda m: m["start"])
    return {"job": job, "moment_count": len(moments), "moments": moments}


def tool_summarize_video(args):
    """Real, honest scope: an EXTRACTIVE summary (the actual highest-
    signal real lines from the transcript, concatenated), not an
    abstractive AI-generated summary — that would need a live LLM API
    call this environment doesn't have wired up. Still genuinely useful
    for a fast overview of what's actually in the video."""
    job = args["job"]
    script = _script_for_job(job)
    if script is None:
        return {"error": f"no transcript found for job '{job}' — check it's finished rough-cut"}

    key_moments_result = tool_get_key_moments({"job": job})
    if "error" in key_moments_result:
        return key_moments_result
    moments = key_moments_result["moments"]

    total_duration = script.get("source_duration_sec", 0)
    highlight_lines = [m["text"] for m in moments if m["text"]][:15]  # cap — a real summary, not a full re-dump
    return {
        "job": job,
        "duration_sec": total_duration,
        "segment_count": len(script.get("kept_segments", [])),
        "key_moment_count": len(moments),
        "extractive_summary": highlight_lines,
    }


TOOLS = {
    "submit_clip_job": {
        "description": "Downloads a video/livestream from a URL (YouTube, Twitch, etc.) and clips it into short highlight videos. Runs in the background — use get_job_status to check progress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Video or livestream URL"},
                "format": {"type": "string", "description": "Output format: short-tiktok-raw, short-explainer, long-form-youtube, square-social, or portrait-social", "default": "short-tiktok-raw"},
                "clip_length": {"type": "integer", "description": "Target clip length in seconds", "default": 60},
                "clip_count": {"type": "integer", "description": "Number of clips to produce", "default": 5},
                "content_type": {"type": "string", "description": "podcast, gaming, or irl — gaming uses letterbox reframe to preserve HUD"},
                "job": {"type": "string", "description": "Optional job id (auto-generated if omitted)"},
            },
            "required": ["url"],
        },
        "fn": tool_submit_clip_job,
    },
    "get_job_status": {
        "description": "Checks the status of a clip job — which of the 7 pipeline steps are done, and any error.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Job id"}},
            "required": ["job"],
        },
        "fn": tool_get_job_status,
    },
    "list_jobs": {
        "description": "Lists all clip jobs and their current status.",
        "inputSchema": {"type": "object", "properties": {}},
        "fn": tool_list_jobs,
    },
    "approve_job": {
        "description": "Approves a job's manual review step so it continues to export. Use after checking get_job_status shows it's paused for review.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Job id"}},
            "required": ["job"],
        },
        "fn": tool_approve_job,
    },
    "list_finished_clips": {
        "description": "Lists finished clip file paths, optionally filtered to one job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Optional job id filter"}},
        },
        "fn": tool_list_finished_clips,
    },
    "publish_to_youtube": {
        "description": "Uploads a finished clip or montage to YouTube with an auto-generated SEO title/description drawn from its real transcript content. Defaults to private (review in YouTube Studio before making public) — pass privacy='public' explicitly to skip that. Requires youtube_client_secret.json already set up.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "description": "Job id of the finished clip/montage subjob (e.g. 'new881__clip01')"},
                "content_type": {"type": "string", "description": "Used for title/tag generation, e.g. 'gaming'", "default": "gaming"},
                "privacy": {"type": "string", "description": "private, unlisted, or public", "default": "private"},
            },
            "required": ["job"],
        },
        "fn": tool_publish_to_youtube,
    },
    "search_video_content": {
        "description": "Searches a job's transcript for a keyword/phrase — real substring match against actual spoken text, returns matching lines with timestamps. Not semantic/AI search.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job": {"type": "string", "description": "Job id"},
                "query": {"type": "string", "description": "Text to search for"},
            },
            "required": ["job", "query"],
        },
        "fn": tool_search_video_content,
    },
    "get_key_moments": {
        "description": "Extracts key moments from a job's video — transcript hooks/highlights, visual motion spikes, and audio gunfire/impact transients, each with real timestamps.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Job id"}},
            "required": ["job"],
        },
        "fn": tool_get_key_moments,
    },
    "summarize_video": {
        "description": "Extractive summary of a job's video — real duration, segment count, and the highest-signal actual transcript lines. Not an AI-generated abstractive summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"job": {"type": "string", "description": "Job id"}},
            "required": ["job"],
        },
        "fn": tool_summarize_video,
    },
}


# ---- JSON-RPC / MCP protocol plumbing ----------------------------------

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "autoclip-pipeline", "version": "1.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # notification, no response expected

    if method == "tools/list":
        tools = [
            {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
            for name, t in TOOLS.items()
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        tool = TOOLS.get(name)
        if not tool:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"}}
        try:
            result = tool["fn"](args)
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": str(e)}}
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
        }

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"unknown method: {method}"}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
