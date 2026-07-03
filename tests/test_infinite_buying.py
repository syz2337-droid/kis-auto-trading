"""사용자가 제공한 라오어 무한매수법 4.0 카페 글의 예시 수치를 그대로 검증한다."""
import pytest

from strategies.infinite_buying import (
    big_number_price,
    build_lower_loc_ladder,
    one_time_buy_amount,
    reverse_portion,
    reverse_sell_qty,
    reverse_star_point,
    should_enter_reverse,
    should_exit_reverse,
    star_pct,
    star_point,
    update_T_general,
    update_T_reverse,
)


def test_star_pct_and_star_point_soxl_20division():
    # 20분할 SOXL, 평단 38.30, T=8.6 -> 별% = 2.8%, 별지점 = 39.37
    pct = star_pct(T=8.6, target_profit_pct=20, division=20)
    assert pct == pytest.approx(2.8)
    assert star_point(38.30, pct) == pytest.approx(39.37, abs=0.01)


def test_star_pct_tqqq_20_and_40division():
    # TQQQ 기준 (목표수익률 15%): 20분할 (15-1.5T)%, 40분할 (15-0.75T)%
    assert star_pct(T=2, target_profit_pct=15, division=20) == pytest.approx(15 - 1.5 * 2)
    assert star_pct(T=2, target_profit_pct=15, division=40) == pytest.approx(15 - 0.75 * 2)


def test_one_time_buy_amount_example():
    # 40분할, 잔금 19522, T=1 -> 19522/39 = 500.5641...
    amount = one_time_buy_amount(cash=19522, division=40, T=1)
    assert amount == pytest.approx(500.5641, abs=0.001)


def test_update_T_general_example():
    # T=7일 때: 1회 다 매수되면 T=8, 절반매수되면 T=7.5, 쿼터매도면 T=5.25
    assert update_T_general(7, full_buy=True, half_buy=False, quarter_sell=False) == pytest.approx(8)
    assert update_T_general(7, full_buy=False, half_buy=True, quarter_sell=False) == pytest.approx(7.5)
    assert update_T_general(7, full_buy=False, half_buy=False, quarter_sell=True) == pytest.approx(5.25)


def test_should_enter_reverse():
    # 20분할은 T>19부터 리버스모드 (T=18.5는 아직 일반모드, T=19.5는 리버스모드)
    assert should_enter_reverse(T=18.5, division=20) is False
    assert should_enter_reverse(T=19.5, division=20) is True
    assert should_enter_reverse(T=39.01, division=40) is True


def test_update_T_reverse_example():
    # 40분할 소진후 T=39.5. 첫날 무조건매도 후 T=37.525. 둘째날 쿼터매수 후 T=38.14375
    t_after_sell = update_T_reverse(39.5, division=40, sold=True, bought=False)
    assert t_after_sell == pytest.approx(37.525, abs=0.001)

    t_after_buy = update_T_reverse(t_after_sell, division=40, sold=False, bought=True)
    assert t_after_buy == pytest.approx(38.14375, abs=0.001)


def test_reverse_star_point_is_5day_average():
    closes = [10, 20, 100, 30, 40, 50]  # 마지막 5개만 사용 (앞의 10은 무시)
    assert reverse_star_point(closes) == pytest.approx((20 + 100 + 30 + 40 + 50) / 5)


def test_should_exit_reverse():
    # 평단 40, SOXL(-20%) 기준선 = 32. 종가가 32보다 커야 종료
    assert should_exit_reverse(last_close=31.9, avg_price=40, exit_pct=20) is False
    assert should_exit_reverse(last_close=32.1, avg_price=40, exit_pct=20) is True


def test_big_number_price_cafe_example():
    # TQQQ 종가 45.93, 12% 위 큰수 = 51.44 (반올림)
    assert big_number_price(45.93, 12) == pytest.approx(51.44, abs=0.001)


def test_lower_loc_ladder_matches_cafe_first_buy_example():
    # 카페 글 처음매수 예시: 40분할 TQQQ, 1회매수액 617.89, 큰수 51.44에 12개 매수.
    # 하방 LOC 7줄(= loc_lines 5 + 2) 가격이 47.53/44.13/41.19/38.61/36.34/34.32/32.52 와 일치해야 한다.
    ladder = build_lower_loc_ladder(budget=617.89, base_qty=12, lines=7, qty_per_line=1)
    expected = [47.53, 44.13, 41.19, 38.61, 36.34, 34.32, 32.52]
    assert [p for p, _ in ladder] == pytest.approx(expected, abs=0.001)
    assert all(q == 1 for _, q in ladder)


def test_lower_loc_ladder_matches_live_site_capture():
    # muhan4.pages.dev 에서 실제 실행 중인 계좌(JS 번들 역산으로 확인)의 전반전 매수 예시:
    # 1회매수금 500.87, 큰수라인 2주 + 평단라인 4주 = 기준수량 6, 하방 8줄.
    ladder = build_lower_loc_ladder(budget=500.87, base_qty=6, lines=8, qty_per_line=1)
    expected = [71.55, 62.60, 55.65, 50.08, 45.53, 41.73, 38.52, 35.77]
    assert [p for p, _ in ladder] == pytest.approx(expected, abs=0.001)


def test_reverse_portion_generalizes_to_30division():
    assert reverse_portion(20) == 10
    assert reverse_portion(40) == 20
    assert reverse_portion(30) == 15


def test_reverse_sell_qty_minimum_one():
    # 보유량이 적어도 쿼터매도처럼 최소 1주는 매도 시도한다
    assert reverse_sell_qty(qty=2, division=40) == 1
    assert reverse_sell_qty(qty=200, division=40) == 10
