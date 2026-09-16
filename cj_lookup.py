import os, requests

EMAIL = os.environ["CJ_EMAIL"]
KEY   = os.environ["CJ_API_KEY"]

s = requests.Session()
auth = s.post(
    "https://developers.cjdropshipping.com/api2.0/v1/authentication/getAccessToken",
    json={"email": EMAIL, "password": KEY}, timeout=30
).json()

if not auth.get("data"):
    print("AUTH FAILED:", auth); raise SystemExit(1)

token = auth["data"]["accessToken"]
pid = "2502080932421628400"

r = s.get(
    "https://developers.cjdropshipping.com/api2.0/v1/product/query",
    headers={"CJ-Access-Token": token},
    params={"pid": pid}, timeout=30
).json()

d = r.get("data") or {}
if not d:
    print("NO DATA:", r); raise SystemExit(1)

for k in ("productNameEn","sellPrice","productWeight","packWeight","productType","sourceFrom","addMarkStatus"):
    print(f"{k:16}", d.get(k))
