#!/bin/bash
# ローカル開発サーバーを起動する
# 使い方: ./start_local.sh

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# .venv がなければ作成
if [ ! -f ".venv/bin/python" ]; then
  echo "=== .venv を作成します ==="
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

# .env がなければ警告
if [ ! -f ".env" ]; then
  echo "⚠️  .env ファイルがありません。OPENAI_API_KEY などが必要な場合は .env を作成してください。"
fi

echo "=== ローカルサーバー起動: http://localhost:5000 ==="
FLASK_ENV=development .venv/bin/python app.py
