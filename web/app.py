"""FastAPI 대시보드 + 자동 스케줄러.

실행: python -m web.app  (또는 uvicorn web.app:app)
http://localhost:8000 에서 세션별 상태 확인 + "오늘 실행" 버튼 사용 가능.
평일 한국시간 16:50 에 자동으로도 한 번 실행된다 (서버가 켜져 있을 때만).

같은 종목이라도 여러 세션(예: TQQQ_1, TQQQ_2)을 독립적으로 운용할 수 있다.
세션별 ⋮ 메뉴에서 설정값 수정, 초기화, 삭제가 가능하다.

UI는 라오어 무한매수법 4.0 계산기(muhan4.pages.dev)의 디자인을 그대로 가져왔다
(JS/CSS 번들을 받아 클래스명·색상·레이아웃을 추출).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from state.store import load_state, save_state
from strategies.base import TickerState
from strategies.infinite_buying import one_time_buy_amount, star_pct as calc_star_pct, star_point as calc_star_point
from web.market_data import get_exchange_rate, get_fear_greed, get_ticker_data
from web.runner import load_raw_config, next_session_id, run_all, save_raw_config

TICKER_PRESETS = {
    "TQQQ": {"target_profit_pct": 15, "exchange": "NASD"},
    "SOXL": {"target_profit_pct": 20, "exchange": "NASD"},
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web.app")

KST = ZoneInfo("Asia/Seoul")
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="무한매수법 자동매매 대시보드")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_run_log: list[dict] = []
_latest_orders: dict[str, list[dict]] = {}
_history: dict[str, list[dict]] = {}

_ORD_DVSN_TAG = {"00": "지정가", "34": "LOC", "33": "MOC"}


def _record_results(results: list[dict], trigger: str) -> None:
    now = datetime.now(KST)
    for r in results:
        if r.get("skipped"):
            continue
        session_id = r["session_id"]
        _latest_orders[session_id] = r.get("orders", [])
        _history.setdefault(session_id, []).insert(
            0,
            {
                "date": now.strftime("%m/%d"),
                "mode": r.get("mode"),
                "summary": f"T={r.get('T')} · 평단 ${r.get('avg_price')} · {r.get('qty')}주",
            },
        )
        _history[session_id] = _history[session_id][:10]
    _run_log.append({"time": now.isoformat(), "trigger": trigger, "results": results})


def _scheduled_run() -> None:
    logger.info("자동 실행 시작 (%s)", datetime.now(KST))
    _record_results(run_all(), "scheduled")


scheduler = BackgroundScheduler(timezone=KST)
scheduler.add_job(
    _scheduled_run,
    CronTrigger(day_of_week="mon-fri", hour=16, minute=50, timezone=KST),
    id="daily_run",
)


@app.on_event("startup")
def _startup() -> None:
    scheduler.start()
    logger.info("스케줄러 시작됨 (평일 16:50 KST 자동 실행)")


@app.on_event("shutdown")
def _shutdown() -> None:
    scheduler.shutdown()


def _render_order(o: dict) -> dict:
    tag = _ORD_DVSN_TAG.get(o["ord_dvsn"], "LOC")
    price = o.get("price")
    return {
        "label": o.get("note") or tag,
        "tag": tag,
        "price": f"${price:,.2f}" if price else "MOC",
        "qty": o["qty"],
    }


def _phase_info(mode: str, qty: int, T: float, division: int) -> tuple[str, str]:
    if mode == "reverse":
        return "리버스", "reverse"
    if qty == 0 and T == 0:
        return "처음매수", "first"
    if T < division / 2:
        return "전반전", "first"
    return "후반전", "second"


def _session_rows() -> list[dict]:
    raw = load_raw_config()
    fx = get_exchange_rate()

    # 종목별 시장 데이터 (같은 종목 여러 세션이 공유)
    unique_tickers = {p.get("ticker", sid) for sid, p in raw.get("sessions", {}).items()}
    mkt = {ticker: get_ticker_data(ticker) for ticker in unique_tickers}

    rows = []
    for session_id, params in raw.get("sessions", {}).items():
        state = load_state(session_id)
        ticker = params.get("ticker", session_id)
        division = params.get("division", 1)
        target_pct = params.get("target_profit_pct", 0)
        phase_label, phase_cls = _phase_info(state.mode, state.qty, state.T, division)
        orders = _latest_orders.get(session_id, [])

        # 별%, 별지점, 1회 매수금 계산
        sp_pct = round(calc_star_pct(state.T, target_pct, division), 2)
        star_pt = calc_star_point(state.avg_price, sp_pct) if state.avg_price > 0 else None
        try:
            buy_amt = round(one_time_buy_amount(state.cash, division, state.T), 2)
        except ValueError:
            buy_amt = None
        buy_amt_krw = round(buy_amt * fx["rate"]) if buy_amt and fx.get("rate") else None

        rows.append(
            {
                "session_id": session_id,
                "label": params.get("label", session_id),
                "ticker": ticker,
                "strategy": params.get("strategy", "infinite_buying"),
                "principal": params.get("principal", 0),
                "division": division,
                "target_profit_pct": target_pct,
                "first_buy_premium_pct": params.get("first_buy_premium_pct"),
                "loc_lines": params.get("loc_lines"),
                "loc_qty_per_line": params.get("loc_qty_per_line"),
                "disable_big_number": params.get("disable_big_number", False),
                "mode": state.mode,
                "phase_label": phase_label,
                "phase_cls": phase_cls,
                "T": round(state.T, 4),
                "progress_pct": min(100, round(state.T / division * 100, 2)) if division else 0,
                "avg_price": state.avg_price,
                "qty": state.qty,
                "cash": round(state.cash, 2),
                "last_run_date": state.last_run_date or "-",
                "is_mock": os.getenv("IS_MOCK", "true"),
                "sell_orders": [_render_order(o) for o in orders if o["side"] == "sell"],
                "buy_orders": [_render_order(o) for o in orders if o["side"] == "buy"],
                "history": _history.get(session_id, []),
                # 신규 필드
                "star_pct_val": sp_pct,
                "star_point_val": star_pt,
                "buy_amount_val": buy_amt,
                "buy_amount_krw": buy_amt_krw,
                "market": mkt.get(ticker, {}),
            }
        )
    return rows


@app.get("/")
def dashboard(request: Request):
    rows = _session_rows()
    if not rows:
        return RedirectResponse(url="/setup")
    fx = get_exchange_rate()
    fear_greed = get_fear_greed()
    return templates.TemplateResponse(request, "dashboard.html", {"rows": rows, "fx": fx, "fear_greed": fear_greed})


@app.post("/run")
def run_now():
    _record_results(run_all(), "manual")
    return RedirectResponse(url="/", status_code=303)


@app.get("/setup")
def setup_form(request: Request):
    return templates.TemplateResponse(request, "setup.html", {"presets": TICKER_PRESETS})


@app.post("/setup")
def setup_submit(
    ticker: str = Form(...),
    division: int = Form(...),
    target_profit_pct: float = Form(...),
    big_number_pct: float = Form(...),
    loc_lines: int = Form(...),
    loc_qty_per_line: int = Form(...),
    principal: float = Form(...),
    entry_mode: str = Form("new"),
    avg_price: float = Form(0),
    qty: int = Form(0),
    cash: float = Form(0),
    t_value: float = Form(0),
):
    ticker = ticker.strip().upper()
    exchange = TICKER_PRESETS.get(ticker, {}).get("exchange", "NASD")

    raw = load_raw_config()
    raw.setdefault("sessions", {})
    session_id = next_session_id(raw, ticker)
    raw["sessions"][session_id] = {
        "ticker": ticker,
        "exchange": exchange,
        "strategy": "infinite_buying",
        "principal": principal,
        "division": division,
        "target_profit_pct": target_profit_pct,
        "loc_lines": loc_lines,
        "loc_qty_per_line": loc_qty_per_line,
        "final_sell_pct": target_profit_pct,
        "reverse_exit_pct": target_profit_pct,
        "first_buy_premium_pct": big_number_pct,
    }
    save_raw_config(raw)

    if entry_mode == "existing":
        state = TickerState(mode="general", T=t_value, avg_price=avg_price, qty=qty, cash=cash)
    else:
        state = TickerState(mode="general", T=0, avg_price=0, qty=0, cash=principal)
    save_state(session_id, state)

    return RedirectResponse(url="/", status_code=303)


@app.post("/session/{session_id}/update")
def session_update(
    session_id: str,
    target_profit_pct: float = Form(...),
    big_number_pct: float = Form(...),
    disable_big_number: bool = Form(False),
    loc_lines: int = Form(...),
    loc_qty_per_line: int = Form(...),
    division: int = Form(...),
    principal: float = Form(...),
    label: str = Form(""),
):
    raw = load_raw_config()
    session = raw.get("sessions", {}).get(session_id)
    if session is None:
        return RedirectResponse(url="/", status_code=303)

    session.update(
        {
            "target_profit_pct": target_profit_pct,
            "first_buy_premium_pct": big_number_pct,
            "disable_big_number": disable_big_number,
            "loc_lines": loc_lines,
            "loc_qty_per_line": loc_qty_per_line,
            "division": division,
            "principal": principal,
            "final_sell_pct": target_profit_pct,
            "reverse_exit_pct": target_profit_pct,
        }
    )
    if label.strip():
        session["label"] = label.strip()
    else:
        session.pop("label", None)
    save_raw_config(raw)
    return RedirectResponse(url="/", status_code=303)


@app.post("/session/{session_id}/reset")
def session_reset(session_id: str):
    raw = load_raw_config()
    session = raw.get("sessions", {}).get(session_id)
    if session is not None:
        save_state(session_id, TickerState(mode="general", T=0, avg_price=0, qty=0, cash=session.get("principal", 0)))
        _latest_orders.pop(session_id, None)
        _history.pop(session_id, None)
    return RedirectResponse(url="/", status_code=303)


@app.post("/session/{session_id}/delete")
def session_delete(session_id: str):
    raw = load_raw_config()
    raw.get("sessions", {}).pop(session_id, None)
    save_raw_config(raw)
    _latest_orders.pop(session_id, None)
    _history.pop(session_id, None)
    state_path = Path(__file__).resolve().parent.parent / "state" / f"{session_id}.json"
    state_path.unlink(missing_ok=True)
    return RedirectResponse(url="/", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=False)
