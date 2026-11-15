"""Automated customer clip delivery (website -> Railway -> email), hardened.

Trust model
  * Jobs arrive ONLY as tickets signed with the website's Ed25519 private key
    (kept in Netlify Blobs, never in this repo). The website's public key is
    fetched once over HTTPS from a fixed URL and pinned on the /data volume.
  * Tickets carry an expiry (<= 15 min) and a one-time nonce (replays refused).
  * Stream URLs are re-validated here: https only, Twitch/Kick/YouTube hosts only.
  * Customer emails never reach this server; jobs are referenced by an opaque id.
  * Completion callbacks to the website are signed with THIS server's Ed25519
    key (also on /data); its public key is served at /api/pubkey.
  * Download links are HMAC-signed by this server with an expiry.
  * Every other /api route still requires ADMIN_TOKEN (see web/main.py).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

router = APIRouter()
PUBLIC_PATHS = ("/api/pubkey", "/api/customer-jobs", "/api/customer-download/")

DATA = os.environ.get("CUSTOMER_DATA_DIR") or ("/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".customer"))
KEYS = os.path.join(DATA, "keys")
STATE = os.path.join(DATA, "customer_jobs.json")
SITE_PUBKEY_URL = os.environ.get("SITE_PUBKEY_URL", "https://takekash.netlify.app/api/pubkey")
SITE_CALLBACK_URL = os.environ.get("SITE_CALLBACK_URL", "https://takekash.netlify.app/api/clip-job-done")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", "https://api.takekash.com")
JID_RE = re.compile(r"^[a-z0-9]{8,40}$")
HOST_RE = re.compile(r"^(www\.|m\.|clips\.)?(twitch\.tv|kick\.com|youtube\.com|youtu\.be)$", re.I)
MAX_TICKET_AGE = 15 * 60
DOWNLOAD_TTL = 7 * 24 * 3600
_lock = threading.RLock()


# ---------- keys ----------

def _read_or_create(path, make):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    if os.path.exists(path):
        return open(path, "rb").read()
    data = make()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return data


def server_key():
    raw = _read_or_create(os.path.join(KEYS, "server_ed25519.raw"),
                          lambda: Ed25519PrivateKey.generate().private_bytes(
                              serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    return Ed25519PrivateKey.from_private_bytes(raw)


def server_pub_b64():
    return base64.b64encode(server_key().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def download_secret():
    return _read_or_create(os.path.join(KEYS, "download_hmac.key"), lambda: secrets.token_bytes(32))


def _fetch_site_pub():
    req = urllib.request.Request(SITE_PUBKEY_URL, headers={"User-Agent": "takekash-api"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return base64.b64decode(json.loads(r.read().decode())["publicKey"])


def site_pub():
    """Website's public key: env pin wins; else first fetch over HTTPS is pinned on the volume."""
    env = os.environ.get("SITE_PUBKEY")
    if env:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(env))
    path = os.path.join(KEYS, "site_ed25519.pub")
    raw = _read_or_create(path, _fetch_site_pub)
    return Ed25519PublicKey.from_public_bytes(raw)


# ---------- state ----------

def _load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"jobs": {}, "nonces": {}}


def _save(st):
    tmp = STATE + ".tmp"
    os.makedirs(DATA, exist_ok=True)
    with open(tmp, "w") as fh:
        json.dump(st, fh)
    os.replace(tmp, STATE)


# ---------- ticket verification ----------

def verify_ticket(body: dict, now=None):
    now = now or time.time()
    try:
        payload_b64, sig_b64 = body["ticket"], body["sig"]
        payload = base64.b64decode(payload_b64, validate=True)
        site_pub().verify(base64.b64decode(sig_b64, validate=True), payload)
        t = json.loads(payload)
    except (KeyError, ValueError, InvalidSignature, TypeError):
        raise HTTPException(401, "invalid signature")
    if not isinstance(t, dict) or t.get("v") != 1:
        raise HTTPException(400, "bad ticket")
    if not (isinstance(t.get("iat"), (int, float)) and isinstance(t.get("exp"), (int, float))):
        raise HTTPException(400, "bad ticket")
    if t["exp"] < now or t["iat"] > now + 60 or t["exp"] - t["iat"] > MAX_TICKET_AGE:
        raise HTTPException(401, "ticket expired")
    jid, url, clips = t.get("jid", ""), t.get("url", ""), t.get("clips")
    if not JID_RE.match(str(jid)) or not isinstance(clips, int) or not (1 <= clips <= 10):
        raise HTTPException(400, "bad ticket")
    u = urllib.parse.urlparse(str(url))
    if u.scheme != "https" or not HOST_RE.match(u.hostname or "") or u.username or u.password or len(url) > 400:
        raise HTTPException(400, "unsupported link")
    with _lock:
        st = _load()
        st["nonces"] = {k: v for k, v in st.get("nonces", {}).items() if v > now}   # drop expired nonces
        if t.get("nonce") in st["nonces"] or jid in st["jobs"]:
            raise HTTPException(409, "ticket already used")
        st["nonces"][t["nonce"]] = t["exp"]
        st["jobs"][jid] = {"url": url, "clips": clips, "status": "queued", "created": now}
        _save(st)
    return t


# ---------- signing out ----------

def sign_download(jid, exp):
    return hmac.new(download_secret(), f"{jid}.{exp}".encode(), hashlib.sha256).hexdigest()


def download_url(jid, now=None):
    exp = int((now or time.time()) + DOWNLOAD_TTL)
    return f"{PUBLIC_BASE}/api/customer-download/{jid}?exp={exp}&sig={sign_download(jid, exp)}"


def signed_callback(payload: dict):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return {"payload": base64.b64encode(raw).decode(), "sig": base64.b64encode(server_key().sign(raw)).decode()}


def post_callback(payload, tries=6):
    body = json.dumps(signed_callback(payload)).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(SITE_CALLBACK_URL, data=body, method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "takekash-api"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if 200 <= r.status < 300:
                    return True
        except Exception as e:
            print(f"customer: callback attempt {i + 1} failed: {e}", flush=True)
        time.sleep(min(300, 5 * 2 ** i))
    return False


# ---------- worker: one job at a time, survives restarts ----------

_worker_started = False


def _run_job(jid):
    from web import main as M
    with _lock:
        st = _load(); job = st["jobs"][jid]; job["status"] = "running"; job["started"] = time.time(); _save(st)
    name = f"cust_{jid}"
    try:
        M._background_clip_run_from_url(name, job["url"], os.environ.get("CUSTOMER_FORMAT", "short-tiktok-raw"),
                                        int(os.environ.get("CUSTOMER_CLIP_LENGTH", "45")), job["clips"], False, "gaming")
        files = M._clip_outputs(name)
    except Exception as e:
        print(f"customer: job {jid} crashed: {e}", flush=True)
        files = []
    status = "done" if files else "failed"
    with _lock:
        st = _load(); st["jobs"][jid].update({"status": status, "delivered": len(files), "finished": time.time()}); _save(st)
    payload = {"v": 1, "jid": jid, "status": status, "delivered": len(files), "iat": int(time.time())}
    if files:
        payload["download"] = download_url(jid)
    ok = post_callback(payload)
    with _lock:
        st = _load(); st["jobs"][jid]["callback"] = "sent" if ok else "failed"; _save(st)


def _worker():
    while True:
        jid = None
        with _lock:
            st = _load()
            # resume anything interrupted by a restart, then oldest queued first
            for k, j in sorted(st["jobs"].items(), key=lambda kv: kv[1].get("created", 0)):
                if j["status"] in ("running", "queued"):
                    jid = k
                    break
        if jid:
            _run_job(jid)
        else:
            time.sleep(5)


def start_worker():
    global _worker_started
    if not _worker_started and os.environ.get("CUSTOMER_WORKER", "on") != "off":
        _worker_started = True
        threading.Thread(target=_worker, daemon=True, name="customer-worker").start()


# ---------- routes ----------

@router.get("/api/pubkey")
def pubkey():
    return {"publicKey": server_pub_b64(), "alg": "Ed25519"}


@router.post("/api/customer-jobs")
async def customer_jobs(request: Request):
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413, "too large")
    try:
        body = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "bad json")
    t = verify_ticket(body)
    start_worker()
    return JSONResponse({"ok": True, "jid": t["jid"], "status": "queued"}, status_code=202)


@router.get("/api/customer-download/{jid}")
def customer_download(jid: str, exp: int = 0, sig: str = ""):
    if not JID_RE.match(jid):
        raise HTTPException(404, "not found")
    if exp < time.time() or not hmac.compare_digest(sig, sign_download(jid, exp)):
        raise HTTPException(403, "link expired or invalid")
    from web import main as M
    files = M._clip_outputs(f"cust_{jid}")
    if not files:
        raise HTTPException(404, "not found")
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i, f in enumerate(files, start=1):
            zf.write(f, arcname=f"takekash_clip_{i:02d}.mp4")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="takekash_clips.zip"', "Cache-Control": "no-store"})
