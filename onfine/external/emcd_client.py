import os, requests, hmac, hashlib, time, decimal
decimal.getcontext().prec = 28

_KEY, _SEC = os.getenv("EMCD_KEY"), os.getenv("EMCD_SECRET").encode()
_BASE = "https://api.emcd.io/v1"

def _sign(p, ts): return hmac.new(_SEC,f"{ts}{p}".encode(),hashlib.sha256).hexdigest()

def _get(path):
    ts=str(int(time.time()))
    r=requests.get(_BASE+path,headers={
        "X-Api-Key":_KEY,"X-Api-Timestamp":ts,"X-Api-Sign":_sign(path,ts)},timeout=10)
    r.raise_for_status(); return r.json()["data"]

def get_today_income_usdt():
    d=_get("/account/balance/history?days=1")[0]
    return decimal.Decimal(d["amount"])
