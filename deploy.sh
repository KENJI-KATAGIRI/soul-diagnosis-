#!/bin/bash
# ローカルで実行: ./deploy.sh
# 魂のナビ講座ディレクトリを VPS の soul-diagnosis に同期し、サービス再起動
# ★ SEO自動改善などで変更されたHTMLを先に取得してから反映（上書き防止）

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
KEY="${HOME}/.ssh/id_ed25519"
HOST="ubuntu@49.212.179.11"
REMOTE="~/apps/soul-diagnosis/"

EXCLUDES=(
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.env'
  --exclude 'data/'
  --exclude '.git/'
  --exclude '.DS_Store'
  --exclude 'terminals/'
)

echo "=== ① VPSの最新HTMLをローカルに取得（SEO改善・手動変更を保持）==="
if [ -f "$KEY" ]; then
  rsync -avz -e "ssh -i $KEY" --include="*.html" --exclude="*" "$HOST:$REMOTE" "$DIR/"
else
  rsync -avz --include="*.html" --exclude="*" "$HOST:$REMOTE" "$DIR/"
fi

echo ""
echo "=== ② ローカルをVPSに反映 ==="
if [ -f "$KEY" ]; then
  rsync -avz -e "ssh -i $KEY" "${EXCLUDES[@]}" "$DIR/" "$HOST:$REMOTE"
  echo ""
  echo "=== ③ サービス再起動（-t で sudo がパスワード入力可能） ==="
  ssh -t -i "$KEY" "$HOST" "cd ~/apps/soul-diagnosis && sudo systemctl restart soul-diagnosis && if sudo systemctl list-unit-files | grep -q '^soul-diagnosis-followup-worker.service'; then sudo systemctl restart soul-diagnosis-followup-worker && sudo systemctl status soul-diagnosis-followup-worker --no-pager; fi && sudo systemctl status soul-diagnosis --no-pager"
else
  echo "鍵 $KEY が見つかりません。-i なしで試行します。"
  rsync -avz "${EXCLUDES[@]}" "$DIR/" "$HOST:$REMOTE"
  ssh -t "$HOST" "cd ~/apps/soul-diagnosis && sudo systemctl restart soul-diagnosis && if sudo systemctl list-unit-files | grep -q '^soul-diagnosis-followup-worker.service'; then sudo systemctl restart soul-diagnosis-followup-worker && sudo systemctl status soul-diagnosis-followup-worker --no-pager; fi && sudo systemctl status soul-diagnosis --no-pager"
fi

echo ""
echo "=== 動作確認URL（ドメインに合わせて読み替え） ==="
echo "  /                     無料診断LP"
echo "  /diagnosis            魂タイプ診断（30問）"
echo "  /premium/ai-report    本格レポート（有料・OpenAI）"
echo "  /soul-nav             魂のナビAI"
echo "  /shindan-ai/          魂のナビ診断AI（5問）"
