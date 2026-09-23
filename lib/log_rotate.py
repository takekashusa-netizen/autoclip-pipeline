"""Size-capped rotation for dashboard.log / poller.log.

Added 2026-09-22 after a real kernel panic (userspace watchdog timeout —
logd stopped checking in for 120s) on the iMac this pipeline runs on.
Disk space and running processes were ruled out as the direct cause, but
dashboard.log/poller.log had no rotation at all: launchd's
StandardOutPath/StandardErrorPath just appends to them forever. This
closes that gap so it's never a contributing factor, without needing any
macOS-level config (newsyslog, launchd plist changes, sudo) — everything
here happens from ordinary file I/O inside this repo.

These two files are NOT written via Python's logging module — launchd
redirects the process's stdout/stderr straight into them at the OS level
(see restart_dashboard.sh / restart_poller.sh, and the plists at
~/Library/LaunchAgents/com.takekash.{dashboard,poller}.plist) — so
logging.handlers.RotatingFileHandler doesn't apply here; there's no
Python-level file handle to swap.

IMPORTANT: rotate_if_needed() truncates IN PLACE rather than renaming.
launchd holds an O_APPEND file descriptor open on the exact path for as
long as the process is alive. A rename-based rotation (the classic
logrotate approach) would silently orphan that fd: the still-running
process would keep appending into the newly-renamed file forever, and
this check would never see it grow again because it's watching the wrong
inode. Truncating in place keeps the same inode, so the next O_APPEND
write from the still-running process lands right after the new, smaller
end-of-file — no service restart required, no lost log handle.
"""
import os


def rotate_if_needed(path, max_bytes=20_000_000, keep_tail_bytes=5_000_000):
    """If `path` has grown past max_bytes, truncate it in place, keeping
    only the most recent keep_tail_bytes of content. Returns True if it
    rotated, False otherwise (file missing, or already under the cap)."""
    if not os.path.exists(path):
        return False
    size = os.path.getsize(path)
    if size < max_bytes:
        return False

    with open(path, "rb") as f:
        f.seek(-min(keep_tail_bytes, size), os.SEEK_END)
        tail = f.read()

    with open(path, "wb") as f:
        f.write(
            f"--- log_rotate.py: truncated at {size/1e6:.1f}MB, kept most "
            f"recent ~{keep_tail_bytes/1e6:.1f}MB ---\n".encode()
        )
        f.write(tail)
    return True
