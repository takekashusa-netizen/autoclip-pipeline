#!/usr/bin/env python3
"""
lib/process_utils.py

Real, single, shared helper for launching detached background
processes. Every file that needs to spawn a long-running job (go.sh,
channel watchers, MCP server actions) should call launch_detached()
here instead of subprocess.Popen()/subprocess.run() directly.

Why this exists: on the night of 2026-09-04, the exact same bug
(missing start_new_session=True) was found and fixed separately in
FIVE different files (cloud_poller.py, lib/channel_watcher.py,
worker/channel_watch.py, mcp_server.py x2). Without process-group
detachment, a launched job's child process stays tied to the
launching shell/process, so closing that terminal or the launcher
exiting kills the job mid-run. Routing every future detached launch
through this one function makes that bug structurally impossible to
reintroduce — there's only one place left to get it right.
"""
import subprocess


def launch_detached(cmd, cwd=None, log_path=None):
    """Real, permanent fix for the process-group kill bug: launches
    cmd as a fully detached background process via start_new_session,
    so it survives the launching shell/process closing or exiting.
    cmd: list of strings (e.g. ["./go.sh", url, "--platform", "interview"])
    cwd: working directory for the launched process (defaults to caller's cwd)
    log_path: if given, both stdout and stderr are appended there;
    otherwise they're discarded (use a real log_path for anything you'll
    need to debug later)
    """
    if log_path:
        log_file = open(log_path, "a")
        stdout = log_file
        stderr = log_file
    else:
        stdout = subprocess.DEVNULL
        stderr = subprocess.DEVNULL

    return subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
