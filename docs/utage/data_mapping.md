# UTAGE連携 — データマッピング

本アプリから UTAGE 受付URL（Webhook）へ送るJSONの**標準フィールド**です。  
UTAGE側の「外部フォーム連携」「Webhook」仕様に合わせて**キー名を環境変数で上書き**できます。

---

## 送信ペイロード（デフォルトキー）

| フィールド | 型 | 説明 | 生成元 |
|------------|-----|------|--------|
| `name` | string | 氏名（任意） | フォーム `name` |
| `email` | string | メール（必須） | フォーム `email` |
| `diagnosis_type` | string | 魂タイプの内部キー | `session.type_quiz_best_key` 例: `intuition_navi` |
| `diagnosis_type_label` | string | 表示名 | `SOUL_TYPES[best_key].name` |
| `energy_score` | number | エネルギー指標（0〜100正規化） | スコア合計から算出※ |
| `problem_category` | string | 悩みカテゴリのラベル | タイプキーからマッピング※ |
| `source` | string | 流入識別子 | 固定 `soul_quiz` または `UTAGE_SOURCE` |
| `scores_json` | string | スコア内訳（JSON文字列） | タイプ名→値の辞書 |

※ `energy_score` / `problem_category` のルールは `utage_integration.py` のヘルパを参照。

---

## problem_category のデフォルト対応（例）

| diagnosis_type | problem_category（例） |
|----------------|-------------------------|
| intuition_navi | direction_clarity |
| strategy_thinker | decision_overload |
| action_breakthrough | effort_mismatch |
| harmony_leader | boundary_clarity |

*運営でカテゴリ名を変える場合はコード内マッピングまたは環境変数拡張で対応。*

---

## UTAGE側で受け取るときの注意

- **読者タグ**に `diagnosis_type` を載せるとセグメント配信に使える  
- **カスタムフィールド**名がプラットフォームで固定の場合、`UTAGE_FIELD_*` でリネーム（実装参照）  

---

## ログ（サーバ）

- 送信成功・失敗はアプリログ＋任意で `data/utage_lead_log.jsonl`（設定時）  

---

## プライバシー

- メール・診断結果は**目的達成に必要な範囲**でUTAGEに渡す  
- プライバシーポリシーに**第三者提供（UTAGE）**を記載すること  
