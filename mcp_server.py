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
