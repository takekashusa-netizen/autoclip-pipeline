"""Customer clip job, run on a free GitHub Actions runner (replaces the paid Railway "api" service).

Flow:  takekash.com (Netlify) signs a job ticket -> GitHub repository_dispatch "customer-job"
       -> this script: verify ticket -> download stream -> clip pipeline -> zip
       -> upload to the storage bucket -> 7-day presigned link -> HMAC-signed callback to the site.

Security:
  * The ticket is Ed25519-signed by the website; we verify it against the site's public key.
  * The callback is HMAC-SHA256 signed with a per-job key ("cbk") the site generated and put inside
    the signed ticket, so no long-lived engine secret exists anywhere.
  * Nothing customer-specific is printed: this repo's Actions logs are public.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SITE_PUBKEY_URL = os.environ.get("SITE_PUBKEY_URL", "https://takekash.netlify.app/api/pubkey")
SITE_CALLBACK_URL = os.environ.get("SITE_CALLBACK_URL", "https://takekash.netlify.app/api/clip-job-done")
JID_RE = re.compile(r"^[a-z0-9]{8,40}$")
HOST_RE = re.compile(r"^(www\.|m\.|clips\.)?(twitch\.tv|kick\.com|youtube\.com|youtu\.be)$", re.I)
MAX_QUEUE_AGE = 60 * 60          # a runner may wait in queue; allow 1h from signing
DOWNLOAD_TTL = 7 * 24 * 3600     # S3 presign maximum


def log(msg):
    print(f"[customer-job] {msg}", flush=True)


def fail(msg, code=1):
    log(msg)
    sys.exit(code)


def site_pub():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pinned = os.environ.get("SITE_PUBKEY")
    if pinned:
        raw = base64.b64decode(pinned)
    else:
        req = urllib.request.Request(SITE_PUBKEY_URL, headers={"User-Agent": "takekash-engine"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = base64.b64decode(json.loads(r.read().decode())["publicKey"])
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_ticket(body, now=None):
    now = now or time.time()
    payload = base64.b64decode(body["ticket"], validate=True)
    site_pub().verify(base64.b64decode(body["sig"], validate=True), payload)   # raises on forgery
    t = json.loads(payload)
    if t.get("v") != 1 or not isinstance(t.get("iat"), (int, float)):
        raise ValueError("bad ticket")
    if t["iat"] > now + 60 or now - t["iat"] > MAX_QUEUE_AGE:
        raise ValueError("ticket expired")
    jid, url, clips, cbk = str(t.get("jid", "")), str(t.get("url", "")), t.get("clips"), t.get("cbk")
    if not JID_RE.match(jid) or not isinstance(clips, int) or not 1 <= clips <= 10:
        raise ValueError("bad ticket")
    if not isinstance(cbk, str) or len(base64.b64decode(cbk)) < 32:
        raise ValueError("ticket has no callback key")
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not HOST_RE.match(u.hostname or "") or u.username or u.password or len(url) > 400:
        raise ValueError("unsupported link")
    return t


def bucket():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=os.environ["BUCKET_ENDPOINT"],
        aws_access_key_id=os.environ["BUCKET_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["BUCKET_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("BUCKET_REGION", "auto"),
        config=Config(signature_version="s3v4", s3={"addressing_style": os.environ.get("BUCKET_ADDRESSING", "virtual")}),
    )


def already_done(s3, key):
    try:
        s3.head_object(Bucket=os.environ["BUCKET_NAME"], Key=key)
        return True
    except Exception:
        return False


def post_callback(cbk_b64, payload, tries=6):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    mac = hmac.new(base64.b64decode(cbk_b64), raw, hashlib.sha256).hexdigest()
    body = json.dumps({"payload": base64.b64encode(raw).decode(), "mac": mac}).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(SITE_CALLBACK_URL, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "takekash-engine"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if 200 <= r.status < 300:
                    log("callback delivered")
                    return True
        except Exception as e:
            log(f"callback attempt {i + 1} failed: {type(e).__name__}")
        time.sleep(min(120, 5 * 2 ** i))
    return False


def main():
    try:
        body = json.loads(os.environ["TICKET"])
        t = verify_ticket(body)
    except Exception as e:
        fail(f"rejected ticket: {type(e).__name__}: {e}", code=2)   # no callback: unverified input
    jid, url, clips, cbk = t["jid"], t["url"], t["clips"], t["cbk"]
    print(f"::add-mask::{url}", flush=True)                           # keep the customer's link out of public logs
    log(f"job {jid}: {clips} clip(s)")

    s3 = bucket()
    key = f"clips/{jid}.zip"
    files = []
    if already_done(s3, key):
        log("already uploaded (re-run); re-sending callback")
        delivered = int(s3.head_object(Bucket=os.environ["BUCKET_NAME"], Key=key).get("Metadata", {}).get("clips", "0"))
    else:
        from web import main as M
        name = f"cust_{jid}"
        try:
            M._background_clip_run_from_url(name, url, os.environ.get("CUSTOMER_FORMAT", "short-tiktok-raw"),
                                            int(os.environ.get("CUSTOMER_CLIP_LENGTH", "45")), clips, False, "gaming")
            files = M._clip_outputs(name)
        except Exception as e:
            log(f"pipeline crashed: {type(e).__name__}")
            files = []
        delivered = len(files)
        if files:
            zpath = os.path.join(ROOT, f"{jid}.zip")
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as zf:
                for i, f in enumerate(files, start=1):
                    zf.write(f, arcname=f"takekash_clip_{i:02d}.mp4")
            s3.upload_file(zpath, os.environ["BUCKET_NAME"], key,
                           ExtraArgs={"ContentType": "application/zip", "Metadata": {"clips": str(delivered)},
                                      "ContentDisposition": 'attachment; filename="takekash_clips.zip"'})
            log(f"uploaded {delivered} clip(s)")

    payload = {"v": 1, "jid": jid, "status": "done" if delivered else "failed", "delivered": delivered, "iat": int(time.time())}
    if delivered:
        payload["download"] = s3.generate_presigned_url("get_object", Params={"Bucket": os.environ["BUCKET_NAME"], "Key": key},
                                                        ExpiresIn=DOWNLOAD_TTL)
    if not post_callback(cbk, payload):
        fail("callback never accepted; site will show the job as processing", code=3)


if __name__ == "__main__":
    main()
