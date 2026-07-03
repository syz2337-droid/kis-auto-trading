"""액면분할 감지 + state 자동 보정.

yfinance의 splits 데이터로 최근 N일 내 분할을 감지하고,
avg_price / qty를 자동으로 보정한 뒤 저장한다.

사용법:
    ratio = check_and_apply("TQQQ_1", "TQQQ")
    if ratio:
        logger.info(f"TQQQ {ratio}:1 분할 감지 — state 보정 완료")
"""
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from state.store import load_state, save_state


def check_and_apply(session_id: str, ticker: str, lookback: int = 3) -> float | None:
    """최근 lookback 거래일 내 액면분할 감지 시 state 보정 후 비율 반환.

    분할 없으면 None 반환.
    """
    splits = yf.Ticker(ticker).splits
    if splits.empty:
        return None

    cutoff = pd.Timestamp(date.today() - timedelta(days=lookback))
    recent = splits[splits.index >= cutoff]
    if recent.empty:
        return None

    ratio = float(recent.iloc[-1])  # 예: 3.0 → 3:1 분할

    state = load_state(session_id)
    if state.avg_price > 0:
        state.avg_price = round(state.avg_price / ratio, 4)
    state.qty = int(state.qty * ratio)
    save_state(session_id, state)

    return ratio
