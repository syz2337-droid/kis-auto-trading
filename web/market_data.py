"""시장 데이터 fetch (환율, 종가 히스토리, 공포&탐욕 지수).

yfinance + 무료 외부 API 사용. 10분 인메모리 캐시.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

import logging

import httpx

logger = logging.getLogger(__name__)
_cache: dict = {}
_TTL = 600  # 10분


def _cached(key: str, fn, *, check=None):
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < _TTL:
        return _cache[key]["data"]
    data = fn()
    # 빈 결과는 캐시하지 않음 (다음 요청 때 재시도)
    if check is None or check(data):
        _cache[key] = {"data": data, "ts": now}
    return data


def get_exchange_rate() -> dict:
    """USD/KRW 환율 (open.er-api.com 무료 API)."""
    def _f():
        try:
            r = httpx.get("https://open.er-api.com/v6/latest/USD", timeout=5)
            d = r.json()
            return {"rate": round(d["rates"]["KRW"], 2), "date": datetime.now().strftime("%Y-%m-%d")}
        except Exception:
            return {"rate": None, "date": None}
    return _cached("fx", _f)


def get_ticker_data(ticker: str) -> dict:
    """종목의 최근 종가 히스토리, OHLC, 1년 차트 데이터."""
    def _f():
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            hist = t.history(period="60d", prepost=True, actions=False)
            if hist.empty:
                hist = t.history(period="60d", actions=False)
            if hist.empty:
                return _empty()

            hist = hist.copy()
            hist["pct"] = hist["Close"].pct_change() * 100

            # 최근 10 거래일 (최신 순)
            recent = list(reversed(list(hist.tail(10).iterrows())))
            closes = []
            for date, row in recent:
                pct = float(row["pct"])
                if math.isnan(pct):
                    pct = 0.0
                closes.append({
                    "date": f"{str(date.year)[2:]}/{date.month:02d}/{date.day:02d}",
                    "close": round(float(row["Close"]), 2),
                    "change_pct": round(pct, 1),
                    "high": round(float(row["High"]), 2),
                    "positive": pct >= 0,
                })

            avg_5 = round(float(hist["Close"].tail(5).mean()), 2)

            # 최신 거래일 OHLC
            last = hist.iloc[-1]
            ld = hist.index[-1]

            # 프리/애프터 마켓 OHLC (1분봉 prepost=True로 추출)
            pre, post = None, None
            try:
                import datetime as _dt
                from zoneinfo import ZoneInfo
                _ET = ZoneInfo("America/New_York")
                intra = t.history(period="1d", interval="1m", prepost=True, actions=False)
                if not intra.empty:
                    et_idx = intra.index.tz_convert(_ET)
                    pre_mask = et_idx.time < _dt.time(9, 30)
                    post_mask = et_idx.time >= _dt.time(16, 0)
                    if pre_mask.any():
                        seg = intra[pre_mask]
                        pre = {
                            "open": round(float(seg["Open"].iloc[0]), 2),
                            "close": round(float(seg["Close"].iloc[-1]), 2),
                            "high": round(float(seg["High"].max()), 2),
                            "low": round(float(seg["Low"].min()), 2),
                        }
                    if post_mask.any():
                        seg = intra[post_mask]
                        post = {
                            "open": round(float(seg["Open"].iloc[0]), 2),
                            "close": round(float(seg["Close"].iloc[-1]), 2),
                            "high": round(float(seg["High"].max()), 2),
                            "low": round(float(seg["Low"].min()), 2),
                        }
            except Exception:
                pass

            ohlc = {
                "date": f"{str(ld.year)[2:]}/{ld.month:02d}/{ld.day:02d}",
                "open": round(float(last["Open"]), 2),
                "high": round(float(last["High"]), 2),
                "low": round(float(last["Low"]), 2),
                "close": round(float(last["Close"]), 2),
                "pre": pre,
                "post": post,
            }

            # 1년 차트 데이터 (실패해도 기본 데이터는 반환)
            chart = {"dates": [], "closes": []}
            s1y: dict = {}
            try:
                hist1y = t.history(period="1y", actions=False)
                if not hist1y.empty:
                    chart = {
                        "dates": [f"{str(d.year)[2:]}/{d.month:02d}/{d.day:02d}" for d in hist1y.index],
                        "closes": [round(float(c), 2) for c in hist1y["Close"]],
                    }
                    s1y = {
                        "min": round(float(hist1y["Close"].min()), 2),
                        "max": round(float(hist1y["Close"].max()), 2),
                        "current": round(float(hist1y.iloc[-1]["Close"]), 2),
                        "change_pct": round(
                            (float(hist1y.iloc[-1]["Close"]) - float(hist1y.iloc[0]["Close"]))
                            / float(hist1y.iloc[0]["Close"]) * 100, 1
                        ),
                    }
            except Exception:
                pass

            return {"closes": closes, "avg_5": avg_5, "ohlc": ohlc, "chart": chart, "stats_1y": s1y, "error": None}
        except Exception as e:
            logger.error("get_ticker_data(%s) 실패: %s", ticker, e)
            return {**_empty(), "error": str(e)}
    return _cached(f"ticker_{ticker}", _f, check=lambda d: bool(d.get("closes")))


def _empty() -> dict:
    return {"closes": [], "avg_5": None, "ohlc": {}, "chart": {"dates": [], "closes": []}, "stats_1y": {}, "error": None}


def get_fear_greed() -> dict:
    """공포&탐욕 지수 현재값 + 30일 히스토리 (alternative.me 무료 API)."""
    def _f():
        try:
            r = httpx.get("https://api.alternative.me/fng/?limit=365", timeout=8)
            items = r.json()["data"]
            cur = items[0]
            v = int(cur["value"])
            history = [
                {"date": _fmt_ts(int(x["timestamp"])), "value": int(x["value"])}
                for x in reversed(items)
            ]
            return {"value": v, "label_ko": _fg_ko(v), "history": history}
        except Exception:
            return {"value": None, "label_ko": "데이터 없음", "history": []}
    return _cached("fg", _f)


def _fg_ko(v: int) -> str:
    if v <= 24: return "극단적 공포"
    if v <= 44: return "공포"
    if v <= 55: return "중립"
    if v <= 74: return "탐욕"
    return "극단적 탐욕"


def _fmt_ts(ts: int) -> str:
    dt = datetime.utcfromtimestamp(ts)
    return f"{str(dt.year)[2:]}/{dt.month:02d}/{dt.day:02d}"
