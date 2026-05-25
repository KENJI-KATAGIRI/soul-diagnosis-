# タスク: UTAGEへの連絡先登録をAPI方式に切り替える

## 背景
現在 lib/utage_integration.py は UTAGE のフォームPOST方式（/r/XXXXX/store）で連絡先登録しているが、
フォームURLが404/405で動いていない。

.mcp.json に UTAGE API の MCP サーバーが設定済みで、Bearer トークンも入っている。
このトークンを使って UTAGE の REST API で連絡先を登録する方式に切り替えたい。

## やること

1. utage-api MCP ツールを使って、以下を確認する
   - 連絡先（コンタクト）を登録するAPIエンドポイントとリクエスト形式
   - 必須パラメータ（メール、名前など）
   - レスポンス形式

2. lib/utage_integration.py の post_utage_lead 関数を修正する
   - フォームPOST方式をやめて、UTAGE REST API（Bearer認証）で連絡先登録する方式に変える
   - Bearer トークンは環境変数 UTAGE_API_KEY から取得する
   - APIのエンドポイントURLは環境変数 UTAGE_API_URL から取得する（デフォルト値も設定）

3. .claude/.env に以下を追加する
   - UTAGE_API_KEY=460a9ac56c2efaf7f14648e8a4cbb781c1cd58a07a7f3f00e478868222a415d7
   - UTAGE_API_URL=（MCPで確認したエンドポイント）

4. 本番サーバー（ubuntu@49.212.179.11:~/apps/soul-diagnosis/.env）にも
   同じキーを追加する手順を教える

5. 動作確認として、テスト用メールアドレスで登録が成功するかAPIを叩いて確認する

## 現在のファイル構成
- lib/utage_integration.py: UTAGE連携の主要ファイル
- .claude/.env: ローカル開発用の環境変数
- .mcp.json: MCP設定（UTAGE APIのBearerトークン入り）
