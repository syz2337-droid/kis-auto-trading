"""전략 공통 인터페이스. 추후 VR(밸류리밸런싱) 전략을 추가할 때 이 인터페이스를 구현한다."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

OrdDvsn = Literal["00", "34", "33"]  # 지정가 / LOC / MOC


@dataclass
class Order:
    side: Literal["buy", "sell"]
    qty: int
    price: float | None  # MOC는 가격 의미 없음 -> None
    ord_dvsn: OrdDvsn
    note: str = ""


@dataclass
class TickerState:
    mode: Literal["general", "reverse"] = "general"
    T: float = 0.0
    avg_price: float = 0.0
    qty: int = 0
    cash: float = 0.0  # 잔금 (다음 1회매수금 계산 기준)
    reverse_day: int = 0  # 리버스모드 진입 후 경과일 (0=처음매도 당일)
    recent_closes: list[float] = field(default_factory=list)  # 최근 종가 (최대 5개, 리버스모드 별지점용)
    last_run_date: str | None = None


@dataclass
class TickerConfig:
    ticker: str
    exchange: str
    principal: float
    division: int
    target_profit_pct: float
    loc_lines: int
    loc_qty_per_line: int
    final_sell_pct: float
    reverse_exit_pct: float
    first_buy_premium_pct: float
    disable_big_number: bool = False  # True면 큰수 안전장치 끄고 항상 별지점만 사용


class Strategy(ABC):
    @abstractmethod
    def compute_orders(self, state: TickerState, quote: dict, config: TickerConfig) -> list[Order]:
        """현재 상태와 시세를 바탕으로 오늘 제출할 주문 목록을 계산한다."""

    @abstractmethod
    def apply_fill_result(self, state: TickerState, fill_summary: dict, config: TickerConfig) -> TickerState:
        """전일 체결 결과를 반영해 다음 상태(T, 평단, 보유량, 잔금, 모드)를 갱신한다."""
