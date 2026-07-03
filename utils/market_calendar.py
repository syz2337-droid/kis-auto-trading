"""NYSE 거래일 확인 유틸리티.

pandas_market_calendars 라이브러리 기반. 휴장일·주말 모두 처리.
is_trading_day() 하나만 쓰면 된다.
"""
from datetime import date

import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")


def is_trading_day(d: date | None = None) -> bool:
    """d가 NYSE 거래일이면 True. 기본값은 오늘(KST 기준)."""
    d = d or date.today()
    return len(_NYSE.valid_days(str(d), str(d))) > 0
