# UTAGE 連携ドキュメント

| ファイル | 内容 |
|----------|------|
| [lp_core_elements.md](./lp_core_elements.md) | 外部LP（本システム）からのコア要素抽出 |
| [utage_lp_variations.md](./utage_lp_variations.md) | UTAGE用サブLP コピー3パターン |
| [ab_test_plan.md](./ab_test_plan.md) | A/Bテスト設計 |
| [funnel_flow.md](./funnel_flow.md) | 外部 → UTAGE 導線 |
| [data_mapping.md](./data_mapping.md) | 送信フィールドとマッピング |
| [setup_guide.md](./setup_guide.md) | 非エンジニア向け設定手順 |
| [strategy_summary.md](./strategy_summary.md) | 戦略サマリー（役割分担・CV要点） |

## アプリ連携（実装）

- `POST /lead/utage` … メール登録時に `UTAGE_LEAD_URL` へ JSON POST
- `GET /result` … 診断セッションから結果再表示
- 環境変数: `README.md` の UTAGE 行を参照
