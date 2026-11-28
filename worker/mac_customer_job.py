"""Mac worker: makes customers' YouTube clips on the owner's Mac (YouTube blocks cloud downloads).

  python3 worker/mac_customer_job.py once        # claim + make any waiting YouTube jobs, then exit
  python3 worker/mac_customer_job.py install     # run `once` every 5 minutes in the background (launchd)
  python3 worker/mac_customer_job.py uninstall
  python3 worker/mac_customer_job.py status

Settings live in ~/.takekash/engine.env (chmod 600), never in the repo:
  TAKEKASH_TOKEN=<Admin Hub sign-in token: Command Center -> Mac worker -> Copy key>   (lasts 30 days)
  BUCKET_ENDPOINT=... BUCKET_NAME=... BUCKET_REGION=auto BUCKET_ACCESS_KEY_ID=... BUCKET_SECRET_ACCESS_KEY=...
Flow per job is identical to the cloud engine: verify the site-signed ticket -> clip pipeline -> zip -> storage
bucket -> 7-day link -> per-job HMAC callback to /api/clip-job-done (the site emails the customer).
"""
import json
import os
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
ENV_FILE = os.path.expanduser("~/.takekash/engine.env")
SITE = os.environ.get("TAKEKASH_SITE", "https://takekash.netlify.app")
LABEL = "com.takekash.macworker"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")
LOG = os.path.expanduser("~/.takekash/macworker.log")
REQUIRED = ["TAKEKASH_TOKEN", "BUCKET_ENDPOINT", "BUCKET_NAME", "BUCKET_ACCESS_KEY_ID", "BUCKET_SECRET_ACCESS_KEY"]


def load_env(path=ENV_FILE):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    return missing


def claim():
    req = urllib.request.Request(f"{SITE}/api/mac-queue", data=b"{}", method="POST",
                                 headers={"Authorization": "Bearer " + os.environ["TAKEKASH_TOKEN"],
                                          "Content-Type": "application/json", "User-Agent": "takekash-mac-worker"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("tickets", [])


def once():
    missing = load_env()
    if missing:
        print(f"[mac-worker] not set up: add {', '.join(missing)} to {ENV_FILE}")
        return 2
    os.environ.setdefault("SITE_CALLBACK_URL", f"{SITE}/api/clip-job-done")
    os.environ.setdefault("SITE_PUBKEY_URL", f"{SITE}/api/pubkey")
    os.environ.setdefault("SITE_PROGRESS_URL", f"{SITE}/api/engine-progress")
    try:
        tickets = claim()
    except urllib.error.HTTPError as e:
        print(f"[mac-worker] site refused the key (HTTP {e.code}): copy a fresh key from the Command Center")
        return 3
    print(f"[mac-worker] claimed {len(tickets)} YouTube job(s)")
    if not tickets:
        return 0
    from worker import actions_customer_job as E         # same verify / clip / upload / callback as the cloud engine
    E.SITE_CALLBACK_URL, E.SITE_PUBKEY_URL, E.SITE_PROGRESS_URL = (os.environ["SITE_CALLBACK_URL"],
                                                                   os.environ["SITE_PUBKEY_URL"], os.environ["SITE_PROGRESS_URL"])
    failed = sum(0 if E.run_ticket(t) else 1 for t in tickets)
    return 1 if failed else 0


def plist_xml(python=sys.executable, root=ROOT):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array><string>{python}</string><string>{root}/worker/mac_customer_job.py</string><string>once</string></array>
  <key>WorkingDirectory</key><string>{root}</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StandardOutPath</key><string>{LOG}</string><key>StandardErrorPath</key><string>{LOG}</string>
</dict></plist>
"""


def install():
    os.makedirs(os.path.dirname(ENV_FILE), exist_ok=True)
    if not os.path.exists(ENV_FILE):
        with os.fdopen(os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT, 0o600), "w") as fh:
            fh.write("# TakeKash Mac worker settings (private)\n" + "".join(f"{k}=\n" for k in REQUIRED) + "BUCKET_REGION=auto\n")
    os.chmod(ENV_FILE, 0o600)
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    open(PLIST, "w").write(plist_xml())
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    subprocess.run(["launchctl", "load", PLIST], check=True)
    missing = load_env()
    print(f"[mac-worker] installed: runs every 5 min, log {LOG}")
    if missing:
        print(f"[mac-worker] still needed in {ENV_FILE}: {', '.join(missing)}")


def uninstall():
    subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
    if os.path.exists(PLIST):
        os.remove(PLIST)
    print("[mac-worker] removed")


def status():
    missing = load_env()
    print(json.dumps({"installed": os.path.exists(PLIST), "settings": ENV_FILE, "missing": missing,
                      "log_tail": open(LOG).read()[-600:] if os.path.exists(LOG) else ""}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    sys.exit({"once": once, "install": install, "uninstall": uninstall, "status": status}[cmd]() or 0)
