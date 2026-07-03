"""라오어 무한매수법 4.0 - 일반모드 + 리버스모드(소진모드) 계산 로직.

API 호출 없는 순수 함수로 작성되어 있어 단위 테스트가 가능하다.

하방 LOC 라인 가격 공식은 카페 글에 명시되어 있지 않아, 실제 계산기 사이트
(muhan4.pages.dev)의 번들 JS를 역산해 알아냈다. 카페 글의 예시 수치(처음매수
TQQQ 40분할 7줄, 전반전 매수 8줄) 및 사이트에서 직접 추출한 실데이터와 모두
소수점까지 정확히 일치함을 확인했다 (tests/test_infinite_buying.py 참고).
"""
from __future__ import annotations

import math
from statistics import mean

from strategies.base import Order, Strategy, TickerConfig, TickerState


def round_half_up(x: float, decimals: int = 2) -> float:
    """JS의 Math.round와 동일한 반올림(0.5는 항상 올림). 파이썬 내장 round()는
    은행가 반올림이라 결과가 미묘하게 달라질 수 있어 별도 구현한다."""
    factor = 10**decimals
    return math.floor(x * factor + 0.5) / factor


def floor2(x: float) -> float:
    """소수점 2자리 절사 (하방 LOC 라인 가격 계산에 사용, 사이트 로직과 동일)."""
    return math.floor(x * 100) / 100


# ---- 일반모드 ----


def star_pct(T: float, target_profit_pct: float, division: int) -> float:
    """별% = 목표수익률 × (1 - 2T/분할수).

    20분할/40분할 공식 (TQQQ: 15-1.5T / 15-0.75T, SOXL: 20-2T / 20-T) 을 일반화한 식이며,
    실제로 두 분할수 모두에서 이 공식과 정확히 일치한다.
    """
    return target_profit_pct * (1 - 2 * T / division)


def star_point(avg_price: float, pct: float) -> float:
    return round_half_up(avg_price * (1 + pct / 100), 2)


def buy_point(point: float) -> float:
    """매수점은 별지점/큰수에서 0.01을 뺀다 (매수·매도 가격 겹침 방지). 평단가
    라인 자체는 이 보정을 적용하지 않고 원래 평단가를 그대로 쓴다."""
    return round_half_up(point - 0.01, 2)


def one_time_buy_amount(cash: float, division: int, T: float) -> float:
    remaining = division - T
    if remaining <= 0:
        raise ValueError("T가 분할수 이상입니다 - 리버스모드로 전환되어야 합니다")
    return cash / remaining


def is_first_half(T: float, division: int) -> bool:
    return T < division / 2


def big_number_price(prev_close: float, premium_pct: float) -> float:
    return round_half_up(prev_close * (1 + premium_pct / 100), 2)


def pick_top_price(star_buy_point: float, big_number: float, disable_big_number: bool) -> tuple[float, str]:
    """별지점(매수점) 가격과 큰수 가격 중, 큰수가 활성화되어 있고 별지점보다
    낮거나 같으면(=더 안전하면) 큰수를 사용한다. (price, label) 을 반환한다."""
    use_big = (not disable_big_number) and big_number > 0 and big_number <= star_buy_point
    return (big_number, "큰수") if use_big else (star_buy_point, "별지점")


def build_lower_loc_ladder(budget: float, base_qty: int, lines: int, qty_per_line: int) -> list[tuple[float, int]]:
    """하방 LOC 라인의 (가격, 수량) 목록.

    price(O) = floor(budget / (base_qty + O*qty_per_line) * 100) / 100, O=1..lines.
    가격이 $1 미만으로 떨어지면 그 줄부터는 만들지 않는다.
    """
    ladder = []
    for o in range(1, lines + 1):
        denom = base_qty + o * qty_per_line
        price = floor2(budget / denom)
        if price < 1:
            break
        ladder.append((price, qty_per_line))
    return ladder


def compute_first_buy_orders(quote: dict, config: TickerConfig) -> list[Order]:
    """보유량 0, T=0 상태의 처음 매수. 종가 대비 first_buy_premium_pct 위를
    '큰수'로 잡아 메인 라인 + (loc_lines+2)줄의 하방 LOC를 깐다."""
    buy_amount = config.principal / config.division
    if buy_amount <= 0:
        return []

    big_number = big_number_price(quote["prev_close"], config.first_buy_premium_pct)
    main_qty = max(1, math.floor(buy_amount / big_number))
    orders = [Order(side="buy", qty=main_qty, price=big_number, ord_dvsn="34", note="처음매수")]

    ladder = build_lower_loc_ladder(buy_amount, main_qty, config.loc_lines + 2, config.loc_qty_per_line)
    orders += [Order(side="buy", qty=q, price=p, ord_dvsn="34", note="") for p, q in ladder]
    return orders


def compute_general_buy_orders(state: TickerState, quote: dict, config: TickerConfig) -> list[Order]:
    buy_amount = one_time_buy_amount(state.cash, config.division, state.T)
    if buy_amount <= 0:
        return []

    pct = star_pct(state.T, config.target_profit_pct, config.division)
    star = star_point(state.avg_price, pct)
    star_buy = buy_point(star)
    big_number = big_number_price(quote["prev_close"], config.first_buy_premium_pct)
    top_price, label = pick_top_price(star_buy, big_number, config.disable_big_number)

    orders: list[Order] = []
    if is_first_half(state.T, config.division):
        half = buy_amount / 2
        n_qty = max(1, math.floor(half / top_price))
        t_full = max(1, math.floor(buy_amount / state.avg_price))
        c_qty = max(1, t_full - n_qty)
        base_qty = n_qty + c_qty
        orders.append(Order(side="buy", qty=n_qty, price=top_price, ord_dvsn="34", note=f"★ {label}"))
        orders.append(Order(side="buy", qty=c_qty, price=state.avg_price, ord_dvsn="34", note="평단가"))
    else:
        base_qty = max(1, math.floor(buy_amount / top_price))
        orders.append(Order(side="buy", qty=base_qty, price=top_price, ord_dvsn="34", note=f"★ {label}"))

    ladder = build_lower_loc_ladder(buy_amount, base_qty, config.loc_lines, config.loc_qty_per_line)
    orders += [Order(side="buy", qty=q, price=p, ord_dvsn="34", note="") for p, q in ladder]
    return orders


def compute_general_sell_orders(state: TickerState, config: TickerConfig) -> list[Order]:
    if state.qty <= 0:
        return []

    pct = star_pct(state.T, config.target_profit_pct, config.division)
    star = star_point(state.avg_price, pct)

    quarter_qty = max(1, math.floor(state.qty / 4))
    rest_qty = state.qty - quarter_qty
    final_price = round_half_up(state.avg_price * (1 + config.final_sell_pct / 100), 2)

    orders = [Order(side="sell", qty=quarter_qty, price=star, ord_dvsn="34", note="★ 쿼터매도")]
    if rest_qty > 0:
        orders.append(Order(side="sell", qty=rest_qty, price=final_price, ord_dvsn="00", note=f"{config.final_sell_pct}% 지정가"))
    return orders


def update_T_general(T: float, full_buy: bool, half_buy: bool, quarter_sell: bool) -> float:
    """1회매수 체결 +1 / 절반매수 체결 +0.5 / 쿼터매도 발생 시 직전T×0.75.

    NOTE: "지정가매도로 전량 종료 후 같은 날 LOC 재매수"가 겹치는 엣지케이스
    (×0.25+1 / ×0.25+0.5)는 아직 반영하지 않았다.
    """
    if quarter_sell:
        T = T * 0.75
    if full_buy:
        T = T + 1
    elif half_buy:
        T = T + 0.5
    return T


def should_enter_reverse(T: float, division: int) -> bool:
    return T > division - 1


# ---- 리버스모드 (소진모드) ----


def reverse_portion(division: int) -> float:
    """리버스모드 매도 등분 비율: 분할수/2 (20분할=10등분, 40분할=20등분,
    30분할=15등분 - 사이트 로직에서 확인된 일반식)."""
    return division / 2


def reverse_sell_qty(qty: int, division: int) -> int:
    if qty <= 0:
        return 0
    return max(1, math.floor(qty / reverse_portion(division)))


def reverse_star_point(recent_closes: list[float]) -> float:
    """리버스모드 별지점 = 직전 5거래일 종가의 평균."""
    last5 = recent_closes[-5:]
    return round_half_up(mean(last5), 2)


def compute_reverse_orders(state: TickerState, quote: dict, config: TickerConfig) -> list[Order]:
    if state.qty <= 0:
        return []

    sell_qty = reverse_sell_qty(state.qty, config.division)

    if state.reverse_day == 0:
        # 처음매도: 무조건매도이므로 별지점 계산 없이 MOC, 매수 없음
        return [Order(side="sell", qty=sell_qty, price=None, ord_dvsn="33", note="MOC 처음매도")] if sell_qty > 0 else []

    star = reverse_star_point(state.recent_closes)
    orders: list[Order] = []
    if sell_qty > 0 and star > 0:
        orders.append(Order(side="sell", qty=sell_qty, price=star, ord_dvsn="34", note="★ 리버스매도"))

    buy_budget = state.cash / 4
    if buy_budget > 0 and star > 0:
        star_buy = buy_point(star)
        big_number = big_number_price(quote["prev_close"], config.first_buy_premium_pct)
        top_price, label = pick_top_price(star_buy, big_number, config.disable_big_number)
        r_qty = max(1, math.floor(buy_budget / top_price))
        orders.append(Order(side="buy", qty=r_qty, price=top_price, ord_dvsn="34", note=f"★ {label} 쿼터매수"))

        ladder = build_lower_loc_ladder(buy_budget, r_qty, config.loc_lines, config.loc_qty_per_line)
        orders += [Order(side="buy", qty=q, price=p, ord_dvsn="34", note="") for p, q in ladder]

    return orders


def update_T_reverse(T: float, division: int, sold: bool, bought: bool) -> float:
    """매도시 20분할 직전T×0.9 / 40분할 직전T×0.95, 매수시 직전T+(분할수-직전T)×0.25.

    NOTE: 30분할 등 다른 분할수의 매도 시 감쇠 비율은 카페 글에 명시되어 있지
    않아 20/40 두 값을 선형보간한 추정치를 사용한다.
    """
    if sold:
        decay = {20: 0.9, 40: 0.95}.get(division, 0.9 + 0.05 * (division - 20) / 20)
        T = T * decay
    if bought:
        T = T + (division - T) * 0.25
    return T


def should_exit_reverse(last_close: float, avg_price: float, exit_pct: float) -> bool:
    """종가가 평단 대비 -exit_pct% 선보다 위로 올라오면 리버스모드 종료."""
    return last_close > avg_price * (1 - exit_pct / 100)


class InfiniteBuyingStrategy(Strategy):
    """Strategy 인터페이스 구현. web/runner.py 에서 이 클래스를 통해 호출한다."""

    def compute_orders(self, state: TickerState, quote: dict, config: TickerConfig) -> list[Order]:
        if state.qty == 0 and state.T == 0 and state.mode == "general":
            return compute_first_buy_orders(quote, config)

        if state.mode == "reverse":
            return compute_reverse_orders(state, quote, config)

        orders = compute_general_buy_orders(state, quote, config)
        orders += compute_general_sell_orders(state, config)
        return orders

    def apply_fill_result(self, state: TickerState, fill_summary: dict, config: TickerConfig) -> TickerState:
        """fill_summary는 web/runner.py 가 실제 체결 내역을 분류해 만든 dict:
        {avg_price, qty, cash, full_buy, half_buy, quarter_sell, sold, bought, last_close}
        """
        state.avg_price = fill_summary.get("avg_price", state.avg_price)
        state.qty = fill_summary.get("qty", state.qty)
        state.cash = fill_summary.get("cash", state.cash)

        last_close = fill_summary.get("last_close")
        if last_close is not None:
            state.recent_closes = (state.recent_closes + [last_close])[-5:]

        if state.mode == "general":
            state.T = update_T_general(
                state.T,
                fill_summary.get("full_buy", False),
                fill_summary.get("half_buy", False),
                fill_summary.get("quarter_sell", False),
            )
            if should_enter_reverse(state.T, config.division):
                state.mode = "reverse"
                state.reverse_day = 0
        else:
            state.T = update_T_reverse(
                state.T,
                config.division,
                fill_summary.get("sold", False),
                fill_summary.get("bought", False),
            )
            state.reverse_day += 1
            if last_close is not None and should_exit_reverse(last_close, state.avg_price, config.reverse_exit_pct):
                state.mode = "general"

        return state
