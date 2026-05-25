#!/usr/bin/env bash
# 週次レポートの自動実行（macOS launchd）をセットアップします
set -euo pipefail

PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/com.gaiaarts.weekly-report.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.gaiaarts.weekly-report.plist"
LOG_DIR="$(cd "$(dirname "$0")" && pwd)/logs"

echo "=== 週次 SEO レポート スケジュール設定 ==="
echo ""

# ログディレクトリ作成
mkdir -p "$LOG_DIR"
echo "[OK] ログディレクトリ作成: $LOG_DIR"

# LaunchAgents にコピー
cp "$PLIST_SRC" "$PLIST_DST"
echo "[OK] plist をコピー: $PLIST_DST"

# すでに登録済みなら一度アンロード
if launchctl list | grep -q "com.gaiaarts.weekly-report" 2>/dev/null; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
  echo "[INFO] 既存のジョブをアンロードしました"
fi

# 登録
launchctl load "$PLIST_DST"
echo "[OK] launchd に登録しました"
echo ""
echo "=== 設定完了 ==="
echo "  実行タイミング : 毎週月曜日 09:00"
echo "  ログファイル   : $LOG_DIR/weekly_report.log"
echo "  エラーログ     : $LOG_DIR/weekly_report_error.log"
echo ""
echo "今すぐテスト実行するには:"
echo "  python weekly_report.py --dry-run    # メール送信せず確認"
echo "  python weekly_report.py              # 実際にメール送信"
echo ""
echo "スケジュール解除するには:"
echo "  launchctl unload $PLIST_DST"
