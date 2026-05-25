# 魂のナビ診断（Flask）

無料診断LPから30問の無料診断へ入り、結果ページから講座LPへ主導線でつなぐ Web アプリです。補助導線として **本格レポート（有料・OpenAI）** と **魂のナビAI（対話）** も利用できます。

## 主なフロー

1. **無料診断LP**（`/`）… 共感ブロックと CTA を置き、主導線を `/diagnosis` に集約。
2. **30問診断**（`/diagnosis` → `POST /result`）… 魂タイプに加え、講座理論・書籍原稿に沿った変容フェーズ・心/魂ナビの寄り・使命まわりの傾向を推定。回答は Flask セッションに保存（約14日）。
3. **結果ページ**（`/result`）… 登録導線（UTAGE有効時）→ 詳細結果表示。主CTAは `/course`（講座LP）、補助CTAは `/premium/ai-report`。
4. **講座LP**（`/course`）… 講座申込への本命ページ。価格・回数・期間・形式・サポート等を表示。
5. **本格レポート（任意）**（`/premium/ai-report`）… アクセスコードまたは `ALLOW_PREMIUM_DEMO=1` で解放後、OpenAI が講座理論＋診断の全回答＋（任意）テーマ・自由記述で長文レポートを生成。旧「自由記述で深掘り（GPT）」はここに統合。本文は `data/premium_reports/` に JSON 保存。
6. **魂のナビAI（任意）**（`/soul-nav`）… 体感ベースの対話（仮説の「向き／ズレ」）。
7. **計測イベントAPI**（`POST /track/event`）… フロントのCTA/送信イベントを収集し、`data/events.jsonl` に保存。
   - **診断から**: `POST /soul-nav/from-diagnosis` … タイプ・スコア＋**診断の一次データ**を `ten_quiz_snapshot` で渡す。
   - **本格レポート直後**: `POST /soul-nav/from-premium-report` … レポート要約＋診断スナップショット（連携モード）。

別系統として **診断AI**（`/shindan-ai/`）、**魂のナビ診断AI** があります。旧 `POST /deep_dive` は本格レポートへリダイレクトします。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
python app.py
```

ブラウザで `http://127.0.0.1:5000` を開いてください（**先に上記を実行し、ターミナルに「Running on ...」が出ていること**が必要です）。

**接続できない・拒否されるとき**

- **開発サーバーが動いていない** … `python app.py` を実行したターミナルを閉じていないか確認する。
- **スマホや別PCから開きたい** … `127.0.0.1` は「そのPC自身」だけです。例: `FLASK_RUN_HOST=0.0.0.0 python app.py` としてから、同じ Wi‑Fi の PC の IP（例 `http://192.168.x.x:5000`）で開く。
- **Remote SSH / コンテナ上で動かしている** … その環境の「ポートフォワード」設定で 5000 を転送するか、SSH トンネル（`ssh -L 5000:127.0.0.1:5000 ...`）を使う。

## 環境変数

| 変数 | 説明 |
|------|------|
| `FLASK_SECRET_KEY` | 本番では必ず設定（セッション署名） |
| `PORT` | 待ち受けポート（既定 5000） |
| `FLASK_RUN_HOST` | `python app.py` 時の待ち受けアドレス（既定 `127.0.0.1`）。別端末から開くときは `0.0.0.0` |
| `OPENAI_API_KEY` | OpenAI 利用時に必須（本格レポート・魂のナビAI） |
| `OPENAI_MODEL` | 既定 `gpt-4o-mini` |
| `PREMIUM_ACCESS_CODE` | 本格レポート解放用の共有コード（未設定時はコード入力フォームは無効） |
| `ALLOW_PREMIUM_DEMO` | `1` で「デモとして解放」ボタンを表示 |
| `SOUL_NAV_DATA_DIR` | 魂のナビAIのセッション JSON 保存先（未設定時は `data/soul_nav_sessions/`） |
| `SOUL_NAV_MIN_USER_CHARS` | 1ターンあたりのユーザー入力の最小文字数（既定 60）。`0` で下限チェックを無効化 |
| `SOUL_NAV_MAX_TOKENS` | 魂のナビAI の OpenAI `max_tokens` 上限（既定 4096、上限 4500 にクランプ） |
| `SOUL_NAV_MIN_OUTPUT_CHARS` | 5項目の**合計**がこの値未満のとき、JSON（`signals`）に `output_below_recommended` 等を記録する（既定 1100）。運用・品質確認用。画面には出さない。`0` で無効化 |
| `SOUL_COURSE_PURCHASE_URL` | 魂のナビ講座の申込・販売ページ URL（未設定時は通常価格ページ `https://lp.tamashiinavi.com/p/normal`） |
| `SOUL_COURSE_CTA_LABEL` | 講座ボタン文言（未設定時は「魂のナビ講座を見る」） |
| `SOUL_COURSE_PRICE` | 講座LPの価格表示（既定 `98,000円（税込）`） |
| `SOUL_COURSE_FORMAT` | 講座LPの形式表示（既定 `オンライン（Zoom）`） |
| `SOUL_COURSE_SESSIONS` | 講座LPの回数表示（既定 `全5回`） |
| `SOUL_COURSE_PERIOD` | 講座LPの期間表示（既定 `90日`） |
| `SOUL_COURSE_SUPPORT` | 講座LPのサポート表示（未設定時は行を非表示。文言を出すときのみ設定） |
| `LINE_REGISTER_URL` | LINE登録ページ URL（未設定時は `https://lp.tamashiinavi.com/p/line`） |
| `DIAGNOSIS_LINE_FUNNEL_URL` | 診断レポート・メールの「次のステップ」先（未設定時は `https://lp.tamashiinavi.com/p/line`） |
| `DIAGNOSIS_LINE_FUNNEL_TITLE` | 上記リンクの見出し文言（未設定時は「LINE登録後に、整え方の動画を受け取る」） |
| `SOUL_COURSE_CAPACITY` | 講座LPの定員表示（既定 `各期12名`） |
| `SOUL_COURSE_BONUS` | 講座LPの特典表示（既定 `Zoom個人セッション（60分）2回`） |
| `SOUL_COURSE_AFTER_APPLY` | 講座LPの申込後フロー表示（既定 `申込完了メール → 個人セッション日程案内 → 初回講座参加`） |
| `CLOSING_COURSE_VIDEO_URL` | 動画視聴ページ URL（未設定時は `https://lp.tamashiinavi.com/p/douga`） |
| `PRIVACY_POLICY_URL` | プライバシーポリシー URL（未設定時は `https://lp.tamashiinavi.com/p/polisy`） |
| `TOKUSHO_URL` | 特商法ページ URL（未設定時は `https://lp.tamashiinavi.com/p/tokusyo`） |
| `COMPANY_URL` | 会社概要 URL（未設定時は `https://lp.tamashiinavi.com/p/co`） |
| `SOUL_COURSE_EARLY_URL` | 早期価格ページ URL（未設定時は `https://lp.tamashiinavi.com/p/first`） |
| `SOUL_COURSE_THANKS_URL` | サンクスページ URL（未設定時は `https://lp.tamashiinavi.com/p/thanx`） |
| `AB_FREE_RESULT_ENABLED` | `1` で無料結果のA/Bテストを有効化（A:定型 / B:強化テンプレ） |
| `AB_FREE_RESULT_B_RATIO` | B配信割合（0-100、既定50） |
| `FOLLOWUP_EMAIL_ENABLED` | `1` で段階フォローメール自動送信を有効化 |
| `FOLLOWUP_RESULT_NO_COURSE_DELAY_MIN` | 結果閲覧後・講座未遷移フォローの遅延（分、既定240） |
| `FOLLOWUP_COURSE_NO_APPLY_DELAY_MIN` | 講座LP閲覧後・未申込フォローの遅延（分、既定1440） |
| `FOLLOWUP_PREMIUM_TO_COURSE_DELAY_MIN` | 本格レポート利用後フォローの遅延（分、既定720） |
| `FOLLOWUP_AI_TO_COURSE_DELAY_MIN` | AI統合利用後フォローの遅延（分、既定720） |
| `EDUCATION_VIDEO_TITLE` | 教育動画の見出し（未設定時は既定文） |
| `EDUCATION_VIDEO_URL` | 教育動画の外部公開 URL。埋め込み未設定時の遷移先 |
| `EDUCATION_VIDEO_EMBED_URL` | 教育動画の埋め込み用 URL（YouTube/Vimeo 等の iframe URL） |
| `NAV_HANDOFF_PAYMENT_LIVE` | `1` のとき、本格レポート内のステップ3案内で「本番では利用条件が異なる場合があります」寄りの文言に切り替え（未設定時は「いまは無料でお試し」） |
| `UTAGE_ENABLED` | `1` かつ `UTAGE_LEAD_URL` があるとき、結果ページにメール登録フォームを表示 |
| `UTAGE_LEAD_URL` | UTAGE の Webhook URL、または UTAGE フォームの `register` / `store` URL |
| `UTAGE_SEND_FORMAT` | 任意。`json` / `form`。未設定時は URL から自動判定（`register` / `store` は `form`） |
| `UTAGE_FORM_RID` | 任意。UTAGE フォーム送信時の hidden `rid`。未設定時、`register` URL ならHTMLから自動取得を試行 |
| `UTAGE_FORM_EMAIL_FIELD` | 任意。UTAGE フォーム送信時のメール欄名（既定 `mail`） |
| `UTAGE_WEBHOOK_SECRET` | 任意。設定時は `Authorization: Bearer …` で送信 |
| `UTAGE_TIMEOUT_SEC` | POST タイムアウト秒（既定 12） |
| `UTAGE_SOURCE` | 送信ペイロードの `source`（既定 `soul_quiz`） |
| `UTAGE_LEAD_LOG` | `1` のとき `data/utage_lead_log.jsonl` に送信成否を追記（`.gitignore` の `data/` 配下） |
| `DIAG_RESULT_EMAIL_ENABLED` | `1` で、登録成功時に診断結果サマリをメール送信 |
| `DIAG_RESULT_EMAIL_DELAY_MIN` | 診断結果メールの送信遅延（分、既定 `5`）。`0` 以下や不正値は **5分** として扱う（即時送信で導線が切れるのを防ぐ） |
| `DIAG_RESULT_EMAIL_SUBJECT` | 送信メール件名（未設定時は既定文） |
| `DIAG_RESULT_EMAIL_BCC` | 任意。結果メールの BCC 送信先 |
| `SMTP_HOST` | SMTP ホスト（例: smtp.gmail.com） |
| `SMTP_PORT` | SMTP ポート（既定 587） |
| `SMTP_USER` | SMTP 認証ユーザー名（未設定ならログインしない） |
| `SMTP_PASS` | SMTP 認証パスワード |
| `SMTP_FROM_EMAIL` | 差出人メールアドレス（必須） |
| `SMTP_FROM_NAME` | 差出人表示名（既定: 魂のナビ診断） |
| `SMTP_REPLY_TO` | 任意。Reply-To アドレス |
| `SMTP_USE_STARTTLS` | `1` で STARTTLS（既定 1） |
| `SMTP_USE_SSL` | `1` で SMTPS 接続（既定 0） |
| `SMTP_TIMEOUT_SEC` | SMTP タイムアウト秒（既定 15） |

詳細は `docs/utage/` を参照してください。

`.env` があれば起動時に読み込みます（`python-dotenv`）。

## データディレクトリ（gitignore）

- `data/premium_reports/` … 本格レポート JSON
- `data/soul_nav_sessions/` … 魂のナビAI セッション
- `data/events.jsonl` … 計測イベントログ
- `data/followup_queue.json` … フォローメールの送信キュー
- `data/followup_state.json` … フォロー抑制（クリック済み等）の状態

`followup_worker.py` を常駐させると、診断結果メールやフォローメールをアクセス有無に依存せず処理できます。VPS では `server/soul-diagnosis-followup-worker.service.example` を systemd に入れる運用を想定しています。

本番デプロイ時はディレクトリの書き込み権限を付与してください。詳細は `DEPLOY.md` を参照。
