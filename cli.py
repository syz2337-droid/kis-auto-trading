"""터미널에서 상태 확인/수동 실행을 하기 위한 디버깅용 진입점.

사용법:
  python cli.py status   # 종목별 현재 상태 출력
  python cli.py run      # 오늘의 매매 실행 (web/runner.py 와 동일 로직)
"""
import argparse
import json

from state.store import load_state
from web.runner import load_raw_config, run_all


def cmd_status() -> None:
    raw = load_raw_config()
    for ticker in raw.get("tickers", {}):
        state = load_state(ticker)
        print(f"[{ticker}] mode={state.mode} T={state.T:.4f} avg={state.avg_price} "
              f"qty={state.qty} cash={state.cash:.2f} last_run={state.last_run_date}")


def cmd_run() -> None:
    results = run_all()
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="무한매수법 자동매매 CLI")
    parser.add_argument("command", choices=["status", "run"])
    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
    elif args.command == "run":
        cmd_run()


if __name__ == "__main__":
    main()
