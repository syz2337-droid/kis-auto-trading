"""해외주식 LOC/MOC/지정가 매수·매도 주문, 잔고조회, 체결내역조회."""
from datetime import date

import httpx

from kis_api.auth import (
    ACCOUNT_NO,
    ACCOUNT_PRODUCT_CD,
    BASE_URL,
    IS_MOCK,
    auth_headers,
    get_hashkey,
)

# 주문구분 코드
ORD_DVSN_LIMIT = "00"  # 지정가
ORD_DVSN_LOO = "32"    # 장개시지정가
ORD_DVSN_LOC = "34"    # 장마감지정가 (LOC)
ORD_DVSN_MOC = "33"    # 장마감시장가 (MOC, 매도 전용)

# 거래소별 매수/매도 TR_ID (실전 우선, 모의는 T-> V 로 치환되는 거래소가 대부분)
_TR_ID = {
    "NASD": {"buy": "TTTT1002U", "sell": "TTTT1006U"},
    "NYSE": {"buy": "TTTT1002U", "sell": "TTTT1006U"},
    "AMEX": {"buy": "TTTT1002U", "sell": "TTTT1006U"},
}


def _tr_id(exchange: str, side: str) -> str:
    tr = _TR_ID.get(exchange, _TR_ID["NASD"])[side]
    return "V" + tr[1:] if IS_MOCK else tr


def place_order(
    symbol: str,
    exchange: str,
    side: str,
    qty: int,
    price: float,
    ord_dvsn: str = ORD_DVSN_LOC,
) -> dict:
    """해외주식 매수/매도 주문을 제출한다.

    side: "buy" | "sell"
    ord_dvsn: ORD_DVSN_LIMIT / ORD_DVSN_LOC / ORD_DVSN_MOC
    MOC는 매도 전용이며, 가격은 의미가 없어 0으로 보낸다.
    """
    body = {
        "CANO": ACCOUNT_NO[:8],
        "ACNT_PRDT_CD": ACCOUNT_PRODUCT_CD,
        "OVRS_EXCG_CD": exchange,
        "PDNO": symbol,
        "ORD_QTY": str(qty),
        "OVRS_ORD_UNPR": "0" if ord_dvsn == ORD_DVSN_MOC else f"{price:.2f}",
        "ORD_SVR_DVSN_CD": "0",
        "ORD_DVSN": ord_dvsn,
    }
    headers = auth_headers(tr_id=_tr_id(exchange, side), extra={"hashkey": get_hashkey(body)})
    resp = httpx.post(
        f"{BASE_URL}/uapi/overseas-stock/v1/trading/order",
        headers=headers,
        json=body,
        timeout=10,
    )
    if not resp.is_success:
        return {"error": True, "status_code": resp.status_code, "body": resp.text[:200]}
    return resp.json()


def get_balance(exchange: str = "NASD", currency: str = "USD") -> dict:
    tr_id = "VTTS3012R" if IS_MOCK else "TTTS3012R"
    resp = httpx.get(
        f"{BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance",
        headers=auth_headers(tr_id=tr_id),
        params={
            "CANO": ACCOUNT_NO[:8],
            "ACNT_PRDT_CD": ACCOUNT_PRODUCT_CD,
            "OVRS_EXCG_CD": exchange,
            "TR_CRCY_CD": currency,
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_executions(start: date, end: date, exchange: str = "NASD") -> dict:
    """기간 내 체결내역을 조회한다 (전일 체결 결과 reconcile용)."""
    tr_id = "VTTS3035R" if IS_MOCK else "TTTS3035R"
    resp = httpx.get(
        f"{BASE_URL}/uapi/overseas-stock/v1/trading/inquire-ccnl",
        headers=auth_headers(tr_id=tr_id),
        params={
            "CANO": ACCOUNT_NO[:8],
            "ACNT_PRDT_CD": ACCOUNT_PRODUCT_CD,
            "OVRS_EXCG_CD": exchange,
            "PDNO": "%",
            "ORD_STRT_DT": start.strftime("%Y%m%d"),
            "ORD_END_DT": end.strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",
            "CCLD_NCCS_DVSN": "01",
            "OVRS_EXCG_CD2": "",
            "SORT_SQN": "DS",
            "ORD_DT": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": "",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
