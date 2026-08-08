#!/usr/bin/env python3
"""
lib/jobstate.py — single source of truth for a job's pipeline state.

Every skill reads/writes through this instead of touching projects/<job>/job.json
directly, so the on-disk schema only has to change in one place. No jq
dependency — plain python3 + json, since that's guaranteed present.

Usage (from shell):
  python3 lib/jobstate.py init      <job> <format> <raw_file>
  python3 lib/jobstate.py get       <job> <dotted.path> [--default X]
  python3 lib/jobstate.py set       <job> <dotted.path> <json_value>
  python3 lib/jobstate.py step-done <job> <step>              # exit 0 if done, 1 if not
  python3 lib/jobstate.py mark      <job> <step> <status> [json_extra]
  python3 jobstate.py path <job>                                # print job.json path
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = [
    "intake", "rough_cut", "graphics", "second_pass",
    "captions", "background_music", "export",
]


def job_dir(job):
    return os.path.join(ROOT, "projects", job)


def job_json_path(job):
    return os.path.join(job_dir(job), "job.json")


def load(job):
    p = job_json_path(job)
    if not os.path.exists(p):
        raise SystemExit(f"no job.json for '{job}' — run init first ({p})")
    with open(p) as f:
        return json.load(f)


def save(job, data):
    p = job_json_path(job)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, p)  # atomic-ish, avoids readers seeing a half-written file


def dotted_get(data, path, default=None):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def dotted_set(data, path, value):
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def cmd_init(job, fmt, raw_file):
    p = job_json_path(job)
    if os.path.exists(p):
        print(f"job.json already exists for '{job}', leaving as-is", file=sys.stderr)
        return
    data = {
        "job": job,
        "format": fmt,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raw": raw_file,
        "steps": {s: {"status": "pending"} for s in STEPS},
        "artifacts": {},
    }
    save(job, data)
    print(job_json_path(job))


def cmd_get(job, path, default):
    data = load(job)
    val = dotted_get(data, path, default)
    print(json.dumps(val))


def cmd_set(job, path, value_json):
    data = load(job)
    dotted_set(data, path, json.loads(value_json))
    save(job, data)


def cmd_step_done(job, step):
    data = load(job)
    status = dotted_get(data, f"steps.{step}.status")
    sys.exit(0 if status == "done" else 1)


def cmd_mark(job, step, status, extra_json):
    data = load(job)
    entry = {"status": status, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if extra_json:
        entry.update(json.loads(extra_json))
    dotted_set(data, f"steps.{step}", entry)
    save(job, data)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    if cmd == "init":
        cmd_init(argv[2], argv[3], argv[4])
    elif cmd == "get":
        default = None
        rest = argv[3:]
        if "--default" in rest:
            i = rest.index("--default")
            default = json.loads(rest[i + 1])
            rest = rest[:i]
        cmd_get(argv[2], rest[0], default)
    elif cmd == "set":
        cmd_set(argv[2], argv[3], argv[4])
    elif cmd == "step-done":
        cmd_step_done(argv[2], argv[3])
    elif cmd == "mark":
        extra = argv[5] if len(argv) > 5 else None
        cmd_mark(argv[2], argv[3], argv[4], extra)
    elif cmd == "path":
        print(job_json_path(argv[2]))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
