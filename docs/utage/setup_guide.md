# UTAGE 設定ガイド（非エンジニア向け）

## 全体像

1. **UTAGE**で「読者を受け取る入口」（フォーム or Webhook URL）を用意する  
2. **本アプリ**の `.env` に、そのURLとトークンを書く  
3. 診断結果ページから**メール登録**ができるようになる  

※ UTAGEの画面名はバージョンで異なる場合があります。**Webhook URL**と**フィールド名**が分かれば設定できます。

---

## 1. UTAGE側：受け口の準備

### パターンA: Webhook（JSON受信）推奨

- 「外部連携」「Webhook」「API」などのメニューから **受信URL** を発行  
- **メソッド**: POST  
- **形式**: JSON（本アプリは `Content-Type: application/json` で送信）  
- 受信後、UTAGEの「読者登録」にマッピングできるか確認  

### パターンB: 従来フォームPOST

- UTAGEが指定する **field名**（例: `mail`）に合わせる  
- 本アプリは `UTAGE_LEAD_URL` に `register` または `store` URL を入れると、`application/x-www-form-urlencoded` での送信に自動対応  
- hidden の `rid` が必要なフォームは、`UTAGE_FORM_RID` に設定するか、`register` URL を使って自動取得させる  

---

## 2. 読者項目・タグ

UTAGEで次を用意できると便利です。

| 項目 | 用途 |
|------|------|
| メール | 必須 |
| 名前 | 任意 |
| カスタム：魂タイプ | `diagnosis_type` |
| カスタム：タイプ表示名 | `diagnosis_type_label` |
| タグ | `source=soul_quiz` などで広告別分析 |

---

## 3. シナリオ（ステップ配信）

- **登録直後**にウェビナー案内・講座オファーのどちらかを送る  
- **タイプ別**に分岐したい場合は、タグ `diagnosis_type` でセグメント  

---

## 4. A/Bテスト（UTAGE）

- **サブLP**を2ページ作り、UTAGEのトラッキングで振り分け  
- 変更は **見出し・CTA・ボタン色** から1つずつ  

---

## 5. 本アプリ側（エンジニア・運用）

1. リポジトリの `.env.example` または README の **環境変数**を参照  
2. `UTAGE_LEAD_URL` に Webhook URL、または UTAGE フォームの `register` / `store` URL  
3. `UTAGE_ENABLED=1`  
4. フォーム型なら必要に応じて `UTAGE_FORM_RID` / `UTAGE_FORM_EMAIL_FIELD` を設定  
5. デプロイ後、**テスト登録**でUTAGEに読者が入るか確認  

---

## トラブルシュート

| 現象 | 確認 |
|------|------|
| 登録フォームが出ない | `UTAGE_ENABLED=1` と `UTAGE_LEAD_URL` |
| 400/403 | UTAGEのトークン・IP制限 |
| 届くが項目が空 | フィールド名の不一致 → `data_mapping.md` とエンジニアに相談 |

---

## やらないこと

- UTAGE管理画面の操作を**スクレイピング**で自動化しない  
- 診断ロジックをUTAGE内に**複製**しない（本アプリが正）  
