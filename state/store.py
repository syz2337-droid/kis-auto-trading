"""종목별 상태를 JSON 파일로 저장/로드한다."""
import json
from dataclasses import asdict
from pathlib import Path

from strategies.base import TickerState

_STATE_DIR = Path(__file__).resolve().parent


def _path(ticker: str) -> Path:
    return _STATE_DIR / f"{ticker}.json"


def load_state(ticker: str) -> TickerState:
    path = _path(ticker)
    if not path.exists():
        return TickerState()
    data = json.loads(path.read_text(encoding="utf-8"))
    return TickerState(**data)


def save_state(ticker: str, state: TickerState) -> None:
    path = _path(ticker)
    path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
