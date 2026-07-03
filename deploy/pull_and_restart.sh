#!/bin/bash
# 코드 배포 스크립트 — 서버에서 실행 (git pull + 서비스 재시작)
# 사용법: bash deploy/pull_and_restart.sh
set -e

APP_DIR="$HOME/kis-auto-trading"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 배포 시작"

cd "$APP_DIR"
git pull origin main

# 새 패키지가 추가됐을 때만 설치
.venv/bin/pip install -r requirements.txt -q

sudo systemctl restart muhan-trading
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 배포 완료"
