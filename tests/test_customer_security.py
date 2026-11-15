"""Attack-style tests for automated customer delivery. Run: python3 tests/test_customer_security.py"""
import base64, json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

site = Ed25519PrivateKey.generate()
attacker = Ed25519PrivateKey.generate()
pub = lambda k: base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
os.environ.update({"SITE_PUBKEY": pub(site), "CUSTOMER_DATA_DIR": tempfile.mkdtemp(), "CUSTOMER_WORKER": "off",
                   "ADMIN_TOKEN": "admin-secret", "PIPELINE_LOCAL": "0"})
from fastapi.testclient import TestClient
from web import main as M, customer as C
client = TestClient(M.app, client=("203.0.113.9", 5555))   # an internet client, not localhost

def ticket(key=site, **over):
    now = int(time.time())
    t = {"v": 1, "jid": base64.b32encode(os.urandom(10)).decode().lower().rstrip("="), "url": "https://www.twitch.tv/videos/123",
         "clips": 3, "iat": now, "exp": now + 600, "nonce": os.urandom(12).hex()}
    t.update(over)
    raw = json.dumps(t).encode()
    return {"ticket": base64.b64encode(raw).decode(), "sig": base64.b64encode(key.sign(raw)).decode()}

passed = 0
def ok(c, m):
    global passed
    if not c: print("FAIL:", m); sys.exit(1)
    passed += 1; print("ok -", m)

post = lambda b: client.post("/api/customer-jobs", json=b)
good = ticket()
ok(post(good).status_code == 202, "valid signed ticket accepted")
ok(post(good).status_code == 409, "replaying the same ticket is refused")
ok(post(ticket(key=attacker)).status_code == 401, "ticket signed by any other key is refused")
t = ticket(); d = json.loads(base64.b64decode(t["ticket"])); d["clips"] = 10; t["ticket"] = base64.b64encode(json.dumps(d).encode()).decode()
ok(post(t).status_code == 401, "tampering with a signed ticket (more clips) is refused")
ok(post(ticket(exp=int(time.time()) - 1)).status_code == 401, "expired ticket refused")
ok(post(ticket(exp=int(time.time()) + 3600)).status_code == 401, "ticket with too-long lifetime refused")
for bad in ["http://www.twitch.tv/videos/1", "https://evil.com/x", "https://user:pw@twitch.tv/x", "file:///etc/passwd",
            "https://twitch.tv.evil.com/x", "https://169.254.169.254/latest"]:
    ok(post(ticket(url=bad)).status_code == 400, f"blocked link: {bad}")
ok(post(ticket(clips=50)).status_code == 400, "clip count capped at 10")
ok(post(ticket(jid="../../etc")).status_code == 400, "job id path tricks refused")
ok(client.post("/api/customer-jobs", content=b"x" * 9000).status_code == 413, "oversized body refused")
ok(post({"ticket": "!!", "sig": "??"}).status_code == 401, "garbage input refused cleanly")

# everything else stays admin-only from the internet
ok(client.get("/api/jobs").status_code == 401, "admin routes still locked without ADMIN_TOKEN")
ok(client.get("/api/jobs", headers={"x-admin-token": "admin-secret"}).status_code == 200, "admin routes open with the token")

# downloads
jid = json.loads(base64.b64decode(good["ticket"]))["jid"]
exp = int(time.time()) + 100
ok(client.get(f"/api/customer-download/{jid}?exp={exp}&sig=deadbeef").status_code == 403, "forged download link refused")
ok(client.get(f"/api/customer-download/{jid}?exp={int(time.time())-5}&sig={C.sign_download(jid, int(time.time())-5)}").status_code == 403, "expired download link refused")
ok(client.get(f"/api/customer-download/{jid}?exp={exp}&sig={C.sign_download(jid, exp)}").status_code == 404, "valid link but no clips yet -> 404 (no leak)")
os.makedirs(M.OUTPUTS, exist_ok=True)
f = os.path.join(M.OUTPUTS, f"cust_{jid}__clip01.final.mp4"); open(f, "wb").write(b"\x00" * 10)
r = client.get(f"/api/customer-download/{jid}?exp={exp}&sig={C.sign_download(jid, exp)}")
ok(r.status_code == 200 and r.content[:2] == b"PK", "valid signed link downloads the zip")
os.remove(f)

# callbacks are verifiable with the published key only
cb = C.signed_callback({"v": 1, "jid": jid, "status": "done"})
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(client.get("/api/pubkey").json()["publicKey"]))
pk.verify(base64.b64decode(cb["sig"]), base64.b64decode(cb["payload"]))
ok(True, "completion callback signature verifies against /api/pubkey")
keyfile = os.path.join(os.environ["CUSTOMER_DATA_DIR"], "keys", "server_ed25519.raw")
ok(oct(os.stat(keyfile).st_mode & 0o777) == "0o600", "private key file is owner-read-only (600)")
print(f"\nALL {passed} CHECKS PASS")
