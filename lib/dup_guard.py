#!/usr/bin/env python3
"""
lib/dup_guard.py

Stops the same moment from being posted twice, even when it was cut by two
different jobs from the same source (e.g. interviewtest vs apexnba2k2).

How it works: every clip's transcript (projects/<job>__windowNN/rough-cut/
script.json) is turned into a set of 5-word sequences. A clip is blocked if
more than THRESHOLD of its 5-word sequences already appear in any clip
recorded as posted on the same platform. The posted record lives in
posted_index.json at the repo root.

Checked 2026-09-26 against the real Cam Capone clips: true repeats scored
27-81%, unrelated clips 0-1%, so 20% is the cut-off.

CLI:
  python3 lib/dup_guard.py check  <content_id> [--platform tiktok]
  python3 lib/dup_guard.py mark   <content_id> [--platform tiktok] [--note "posted by hand"]
  python3 lib/dup_guard.py list
content_id can be any of: apexnba2k2__window07, apexnba2k2_window07_tiktok, ...
"""
import json
import os
import re
import sys
import zlib
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_FILE = os.path.join(ROOT, "posted_index.json")
THRESHOLD = 0.20
N = 5


def project_dir(content_id):
    """'interviewtest_window12_tiktok' / 'interviewtest__window12' -> 'interviewtest__window12'."""
    m = re.match(r"^(.+?)_{1,2}window(\d+)", content_id)
    return f"{m.group(1)}__window{int(m.group(2)):02d}" if m else content_id


def _words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def fingerprint(content_id):
    """Sorted list of crc32 hashes of the clip's 5-word sequences, or None
    when no transcript exists (gameplay clips with no speech, etc.)."""
    path = os.path.join(ROOT, "projects", project_dir(content_id), "rough-cut", "script.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        d = json.load(f)
    w = _words(" ".join(s.get("text", "") for s in d.get("kept_segments", [])))
    if len(w) < N * 4:
        return None
    return sorted({zlib.crc32(" ".join(w[i:i + N]).encode()) for i in range(len(w) - N + 1)})


def _load():
    if not os.path.exists(INDEX_FILE):
        return []
    with open(INDEX_FILE) as f:
        return json.load(f)


def _save(entries):
    tmp = INDEX_FILE + ".partial"
    with open(tmp, "w") as f:
        json.dump(entries, f)
    os.replace(tmp, INDEX_FILE)


def check(content_id, platform="tiktok"):
    """Returns (ok, reason). ok=False means a matching clip is already posted."""
    pid = project_dir(content_id)
    fp = fingerprint(content_id)
    entries = [e for e in _load() if e["platform"] == platform]
    if any(e["project"] == pid for e in entries):
        return False, f"{pid} is already recorded as posted on {platform}"
    if fp is None:
        return True, "no transcript to compare (allowed)"
    mine = set(fp)
    worst = (0.0, None)
    for e in entries:
        if not e.get("fp"):
            continue
        share = len(mine & set(e["fp"])) / len(mine)
        if share > worst[0]:
            worst = (share, e)
    if worst[0] > THRESHOLD:
        e = worst[1]
        return False, (f"{worst[0]:.0%} of {pid}'s words match {e['project']} "
                       f"(posted {e['posted_at'][:10]} on {platform})")
    return True, f"max overlap {worst[0]:.0%}"


def mark(content_id, platform="tiktok", note="", result=None, posted_at=None):
    pid = project_dir(content_id)
    entries = [e for e in _load() if not (e["project"] == pid and e["platform"] == platform)]
    entries.append({"project": pid, "platform": platform, "posted_at": posted_at or datetime.now().isoformat(),
                    "note": note, "result": result, "fp": fingerprint(content_id)})
    _save(entries)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "mark", "list"])
    ap.add_argument("content_id", nargs="?")
    ap.add_argument("--platform", default="tiktok")
    ap.add_argument("--note", default="")
    a = ap.parse_args()
    if a.cmd == "list":
        for e in _load():
            print(e["platform"], e["project"], e["posted_at"][:16], e.get("note", ""))
    elif not a.content_id:
        sys.exit("content_id required")
    elif a.cmd == "check":
        ok, why = check(a.content_id, a.platform)
        print(("OK  " if ok else "DUPLICATE  ") + why)
        sys.exit(0 if ok else 1)
    else:
        mark(a.content_id, a.platform, a.note)
        print(f"marked {project_dir(a.content_id)} as posted on {a.platform}")
