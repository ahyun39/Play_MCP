#!/bin/bash
# FoodMCP 원커맨드 실행: ./run.sh  (포트 변경: PORT=8765 ./run.sh)
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "[FoodMCP] 가상환경 생성 중..."
    python3 -m venv .venv
fi

echo "[FoodMCP] 의존성 설치 중..."
.venv/bin/pip install -q -r requirements.txt

PORT="${PORT:-8000}"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "[FoodMCP] 오류: $PORT 포트가 이미 사용 중입니다. 다른 포트로 실행하세요: PORT=8765 ./run.sh"
    exit 1
fi

echo "[FoodMCP] 서버 시작 → http://localhost:$PORT/mcp"
exec .venv/bin/python server.py
