#!/usr/bin/env bash
# バックエンドAPIとフロントエンド開発サーバーをまとめて起動する。Ctrl+Cで両方停止する。
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ ! -x backend/.venv/bin/python ]; then
  echo "backend/.venv がありません。backend で仮想環境を作成し、pip install -r requirements.txt を実行してください。" >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "frontend/node_modules がありません。frontend で pnpm install を実行してください。" >&2
  exit 1
fi

# Ctrl+C・異常終了のどちらでも、プロセスグループごと確実に停止する。
cleanup() {
  trap - INT TERM EXIT
  kill 0
}
trap cleanup INT TERM EXIT

(cd backend && exec .venv/bin/python -m app.api) 2>&1 | awk '{ print "[api] " $0; fflush() }' &
(cd frontend && exec pnpm dev) 2>&1 | awk '{ print "[web] " $0; fflush() }' &

wait
