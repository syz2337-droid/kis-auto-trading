"""해외주식 현재가/전일종가 조회."""
import httpx

from kis_api.auth import BASE_URL, auth_headers

# 해외거래소 코드 (한투 기준): 나스닥 NAS, 뉴욕 NYS, 아멕스 AMS
EXCHANGE_CODE = {
    "NASD": "NAS",
    "NYSE": "NYS",
    "AMEX": "AMS",
}


def get_quote(symbol: str, exchange: str = "NASD") -> dict:
    """현재가/전일종가 등을 조회한다.

    실제 응답 필드는 한투 API 문서(HHDFS00000300)를 기준으로 하며,
    last=현재가(직전 체결가), base=전일종가로 사용한다.
    """
    excd = EXCHANGE_CODE.get(exchange, "NAS")
    resp = httpx.get(
        f"{BASE_URL}/uapi/overseas-price/v1/quotations/price",
        headers=auth_headers(tr_id="HHDFS00000300"),
        params={"AUTH": "", "EXCD": excd, "SYMB": symbol},
        timeout=10,
    )
    resp.raise_for_status()
    output = resp.json()["output"]
    return {
        "symbol": symbol,
        "last": float(output["last"]),
        "prev_close": float(output["base"]),
        "raw": output,
    }
