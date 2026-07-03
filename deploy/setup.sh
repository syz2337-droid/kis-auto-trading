#!/bin/bash
# 서버 최초 설치 스크립트 (Ubuntu 22.04 기준 — Oracle/GCP 공통)
# 사용법: bash deploy/setup.sh
set -e

REPO_URL="https://github.com/syz2337-droid/kis-auto-trading.git"
APP_DIR="$HOME/kis-auto-trading"
PYTHON="python3"

echo "=== [1/5] 패키지 업데이트 ==="
sudo apt update -y && sudo apt install -y python3 python3-venv git

echo "=== [2/5] 저장소 클론 ==="
git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"

echo "=== [3/5] 가상환경 + 의존성 설치 ==="
$PYTHON -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "=== [4/5] .env 파일 생성 ==="
if [ ! -f .env ]; then
    cp .env.example .env
    echo "→ .env 파일을 편집하세요: nano $APP_DIR/.env"
fi

echo "=== [5/5] systemd 서비스 등록 ==="
# 서비스 파일의 경로를 실제 홈 디렉토리로 치환 후 복사
sed "s|{APP_DIR}|$APP_DIR|g; s|{USER}|$USER|g" \
    deploy/muhan-trading.service \
    | sudo tee /etc/systemd/system/muhan-trading.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable muhan-trading
sudo systemctl start muhan-trading

echo ""
echo "=== 설치 완료 ==="
echo "상태 확인: sudo systemctl status muhan-trading"
echo "로그 확인: sudo journalctl -u muhan-trading -f"
echo "대시보드:  http://서버IP:8000"
