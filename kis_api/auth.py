"""한투 OpenAPI 인증: 접근토큰 발급/캐싱, 모의/실전 base URL 분기."""
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

IS_MOCK = os.getenv("IS_MOCK", "true").lower() == "true"
APP_KEY = os.getenv("KIS_APP_KEY", "")
APP_SECRET = os.getenv("KIS_APP_SECRET", "")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
ACCOUNT_PRODUCT_CD = os.getenv("KIS_ACCOUNT_PRODUCT_CD", "01")

BASE_URL = "https://openapivts.koreainvestment.com:29443" if IS_MOCK else "https://openapi.koreainvestment.com:9443"

_TOKEN_CACHE_PATH = Path(__file__).resolve().parent.parent / "state" / "_token_cache.json"


def _load_cached_token() -> str | None:
    if not _TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(_TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("expires_at", 0) - 60 <= time.time():
        return None
    return data.get("access_token")


def _save_token_cache(access_token: str, expires_in: int) -> None:
    _TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE_PATH.write_text(
        json.dumps({"access_token": access_token, "expires_at": time.time() + expires_in}),
        encoding="utf-8",
    )


def get_access_token() -> str:
    """캐시된 토큰이 유효하면 재사용하고, 없으면 새로 발급받는다."""
    cached = _load_cached_token()
    if cached:
        return cached

    resp = httpx.post(
        f"{BASE_URL}/oauth2/tokenP",
        json={
            "grant_type": "client_credentials",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_token_cache(data["access_token"], data["expires_in"])
    return data["access_token"]


def get_hashkey(body: dict) -> str:
    """주문 등 POST 요청 바디 무결성 검증용 hashkey 발급."""
    resp = httpx.post(
        f"{BASE_URL}/uapi/hashkey",
        headers={
            "content-type": "application/json",
            "appkey": APP_KEY,
            "appsecret": APP_SECRET,
        },
        json=body,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["HASH"]


def auth_headers(tr_id: str, extra: dict | None = None) -> dict:
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {get_access_token()}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }
    if extra:
        headers.update(extra)
    return headers
