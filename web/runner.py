"""일일 실행 흐름: 전일 체결 reconcile -> 오늘 주문 계산 -> 제출.

세션(session) 단위로 동작한다. 세션은 "종목 + 분할수 + 전략 설정"의 한 묶음으로,
같은 종목이라도 여러 세션(예: TQQQ_1, TQQQ_2)을 동시에 운용할 수 있다.

NOTE: 한투 잔고조회(inquire-balance) 응답의 정확한 필드명(ovrs_pdno, ovrs_cblc_qty,
pchs_avg_pric 등)은 API 키 발급 후 실제 응답으로 검증/보정이 필요하다.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from kis_api import order as kis_order
from kis_api import quote as kis_quote
from state.store import load_state, save_state
from strategies.base import Order, TickerConfig
from strategies.infinite_buying import InfiniteBuyingStrategy
from utils.market_calendar import is_trading_day
from utils import split_detector

KST = ZoneInfo("Asia/Seoul")
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

STRATEGIES = {"infinite_buying": InfiniteBuyingStrategy()}


def load_raw_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {"sessions": {}}


def save_raw_config(raw: dict) -> None:
    CONFIG_PATH.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")


def next_session_id(raw: dict, ticker: str) -> str:
    """같은 종목의 기존 세션 수를 보고 다음 번호를 붙인다 (TQQQ_1, TQQQ_2, ...)."""
    existing = raw.get("sessions", {})
    n = 1
    while f"{ticker}_{n}" in existing:
        n += 1
    return f"{ticker}_{n}"


def _session_config(params: dict) -> TickerConfig:
    params = dict(params)
    for key in ("strategy", "label", "enabled"):
        params.pop(key, None)
    return TickerConfig(**params)


def _today_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _reconcile_fill_summary(ticker: str, exchange: str, division: int, T: float, cash: float, last_close: float | None) -> dict:
    """실제 잔고를 조회해 보유량/평단을 갱신하고, 의도했던 매수금 대비 체결 비율로
    full_buy/half_buy/quarter_sell 을 추정한다."""
    balance = kis_order.get_balance(exchange=exchange)
    holdings = {h["ovrs_pdno"]: h for h in balance.get("output1", [])}
    info = holdings.get(ticker)

    new_qty = int(info["ovrs_cblc_qty"]) if info else 0
    new_avg = float(info["pchs_avg_pric"]) if info else 0.0

    return {
        "avg_price": new_avg,
        "qty": new_qty,
        "cash": cash,
        "last_close": last_close,
        "raw_balance": info,
    }


def run_daily(session_id: str, raw_cfg: dict) -> dict:
    config = _session_config(raw_cfg)
    strategy = STRATEGIES[raw_cfg.get("strategy", "infinite_buying")]

    if not is_trading_day():
        return {"session_id": session_id, "ticker": config.ticker, "skipped": True, "reason": "NYSE 휴장일"}

    state = load_state(session_id)

    today = _today_str()
    if state.last_run_date == today:
        return {"session_id": session_id, "ticker": config.ticker, "skipped": True, "reason": "오늘 이미 실행됨"}

    quote = kis_quote.get_quote(config.ticker, exchange=config.exchange)

    if state.last_run_date is not None:
        # 첫 실행이 아니면, 전일 체결 결과를 broker 잔고 기준으로 반영한다.
        fill_summary = _reconcile_fill_summary(
            config.ticker, config.exchange, config.division, state.T, state.cash, quote["prev_close"]
        )
        # NOTE: full_buy/half_buy/quarter_sell 판정 로직은 실제 체결 데이터로
        # 보강이 필요하다. 현재는 broker 잔고 변화만 반영하고 T는 그대로 둔다.
        state.avg_price = fill_summary["avg_price"] or state.avg_price
        state.qty = fill_summary["qty"]
        state.recent_closes = (state.recent_closes + [quote["prev_close"]])[-5:]

    if state.qty == 0 and state.cash == 0:
        state.cash = config.principal  # 최초 실행: 원금 전액을 잔금으로 시작

    # 액면분할 감지 시 avg_price·qty 자동 보정 후 state 재로드
    if split_detector.check_and_apply(session_id, config.ticker):
        state = load_state(session_id)

    orders = strategy.compute_orders(state, quote, config)

    submitted = []
    for o in orders:
        result = kis_order.place_order(
            symbol=config.ticker,
            exchange=config.exchange,
            side=o.side,
            qty=o.qty,
            price=o.price or 0,
            ord_dvsn=o.ord_dvsn,
        )
        submitted.append({"order": asdict(o), "result": result})
        time.sleep(0.5)  # KIS API 초당 거래건수 제한 회피

    state.last_run_date = today
    save_state(session_id, state)

    current_price = quote.get("price") or quote.get("prev_close") or 0
    return {
        "session_id": session_id,
        "ticker": config.ticker,
        "skipped": False,
        "mode": state.mode,
        "T": state.T,
        "avg_price": state.avg_price,
        "qty": state.qty,
        "cash": state.cash,
        "current_price": current_price,
        "orders": [asdict(o) for o in orders],
        "submitted": submitted,
    }


def run_all() -> list[dict]:
    raw = load_raw_config()
    results = []
    for session_id, params in raw.get("sessions", {}).items():
        if not params.get("enabled", True):
            results.append({"session_id": session_id, "ticker": params.get("ticker", session_id), "skipped": True, "reason": "비활성화됨"})
            continue
        results.append(run_daily(session_id, params))
    return results
