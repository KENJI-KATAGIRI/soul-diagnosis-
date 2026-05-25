# VPS へのアップロード（デプロイ）手順

ローカル（Mac）で開発したコードを **VPS 上の `~/apps/soul-diagnosis/`** に同期し、**systemd サービス `soul-diagnosis`** を再起動して反映します。

---

## 全体の流れ

1. Mac でプロジェクトを編集・コミット（任意）
2. **`rsync`** で VPS にファイルを上書き同期（SSH 経由）
3. VPS で **`sudo systemctl restart soul-diagnosis`** でアプリ再起動
4. フォローメールを時刻どおり送りたい場合は **`soul-diagnosis-followup-worker`** も有効化
5. ブラウザで本番 URL を開いて確認

**重要:** `rsync` と `ssh` は **自分の Mac のターミナル** で実行します。VPS にログインしてから Mac のパスで `rsync` しても動きません。

---

## 前提条件（初めての前に確認）

| 項目 | 内容 |
|------|------|
| SSH | VPS のユーザー（例: `ubuntu`）に **公開鍵認証** で入れること |
| 鍵の場所 | 多くの環境で `~/.ssh/id_ed25519` または `~/.ssh/id_rsa` |
| リモートパス | 例: `~/apps/soul-diagnosis/`（`deploy.sh` の `REMOTE` と一致） |
| サービス名 | `soul-diagnosis`（`systemctl` 用） |
| サーバー側 Python | 仮想環境 `.venv` を **サーバー上で作成**し、`requirements.txt` をインストール済みであること |

初回だけサーバーで次のような準備が必要です（既に済んでいれば不要）。

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@YOUR_SERVER_IP
mkdir -p ~/apps/soul-diagnosis
cd ~/apps/soul-diagnosis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# 書き込み用（本格レポート・魂のナビセッション）
mkdir -p data/premium_reports data/soul_nav_sessions
```

**`.env` はサーバー上だけに置く**（`rsync` の exclude で送らない）。例:

```bash
nano ~/apps/soul-diagnosis/.env
```

最低限の例（本番では強い `FLASK_SECRET_KEY` を使う）:

```
FLASK_SECRET_KEY=（ランダムな長い文字列）
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
PREMIUM_ACCESS_CODE=（任意）
# 検証時だけ: ALLOW_PREMIUM_DEMO=0
```

systemd ユニット（`soul-diagnosis.service`）は、リポジトリ外で VPS に既にある前提です。`WorkingDirectory` が `~/apps/soul-diagnosis`、`ExecStart` がその下の `.venv` の gunicorn 等を指すようにします。

**本格レポート生成**は OpenAI 応答待ちで **30秒を超えがち**です。Gunicorn の既定タイムアウト（例: 30 秒）のままだとワーカーが切られ、ブラウザでは「反応がない／502」に見えます。`ExecStart` の gunicorn に **`--timeout 120`**（以上）を付けることを推奨します。

診断結果メールや段階フォローを**アクセスが無い時間帯でも送る**には、別プロセスの worker を使うのが安全です。リポジトリには `followup_worker.py` と `server/soul-diagnosis-followup-worker.service.example` を入れてあります。

### フォローアップ worker を有効化

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@YOUR_SERVER_IP
cd ~/apps/soul-diagnosis
sudo cp server/soul-diagnosis-followup-worker.service.example /etc/systemd/system/soul-diagnosis-followup-worker.service
# 必要なら User / Group / WorkingDirectory / ExecStart をサーバー環境に合わせて編集
sudo systemctl daemon-reload
sudo systemctl enable --now soul-diagnosis-followup-worker
sudo systemctl status soul-diagnosis-followup-worker --no-pager
```

診断結果メールは既定で **5分後**にキュー送信です。worker が 30 秒間隔で回るため、実際の配信は「約5分後から最大30秒程度のズレ」で送られます。

---

## 方法1: `./deploy.sh`（推奨）

### 1. スクリプトを自分の環境に合わせる

`deploy.sh` 内の次の変数を確認・変更します。

| 変数 | 意味 |
|------|------|
| `KEY` | SSH 秘密鍵のパス（例: `~/.ssh/id_ed25519`） |
| `HOST` | `ユーザー@サーバーIP`（例: `ubuntu@49.212.179.11`） |
| `REMOTE` | VPS 上の同期先（例: `~/apps/soul-diagnosis/`） |

### 2. Mac で実行

```bash
cd "/Users/katagirikenji/魂のナビ講座"
chmod +x deploy.sh
./deploy.sh
```

### 3. スクリプトが行うこと

1. **`rsync -avz`** でローカル `DIR/` の中身を `HOST:REMOTE` に同期  
2. **除外されるもの**（サーバー側の環境・データを壊さないため）  
   - `.venv/` … サーバー側の仮想環境を使う  
   - `.env` … 秘密情報はサーバーだけで管理  
   - `data/` … 生成データ・セッションはデプロイで上書きしない  
   - `.git/`、`__pycache__/`、`.pyc`、`.DS_Store` など  
3. **`ssh -t`** で VPS に入り、`sudo systemctl restart soul-diagnosis` を実行  
4. `soul-diagnosis-followup-worker` が入っていれば自動で再起動  

**`ssh -t` の理由:** 一部の環境では `sudo` が TTY を要求するため、`-t` で疑似端末を付けます。パスワード付き `sudo` の場合は、プロンプトが表示されます。

### 4. 同期「される」主なもの（参考）

- `app.py`、`premium_report.py`
- `templates/`、`static/`、`nav_diagnosis_ai/`、`soul_nav_ai/`
- `requirements.txt`、`deploy.sh`、`README.md` などプロジェクト内の通常ファイル

`requirements.txt` を変更した場合は、**デプロイ後に VPS で一度だけ**:

```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@YOUR_SERVER_IP
cd ~/apps/soul-diagnosis && source .venv/bin/activate && pip install -r requirements.txt
```

---

## 方法2: 手動 rsync + ssh（スクリプトを使わない場合）

パスと鍵は環境に合わせて読み替えてください。

```bash
LOCAL="/Users/katagirikenji/魂のナビ講座"
KEY="$HOME/.ssh/id_ed25519"
HOST="ubuntu@49.212.179.11"
REMOTE="~/apps/soul-diagnosis/"

rsync -avz -e "ssh -i $KEY" \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  "$LOCAL/" "$HOST:$REMOTE"

ssh -t -i "$KEY" "$HOST" \
  "cd ~/apps/soul-diagnosis && sudo systemctl restart soul-diagnosis && sudo systemctl status soul-diagnosis --no-pager"
```

---

## 方法3: Cursor / VS Code Remote SSH

1. Remote SSH で VPS に接続  
2. エディタやファイルパネルから `~/apps/soul-diagnosis/` に、ローカルと同じ構成でファイルをコピー・編集  
3. ターミナルで `sudo systemctl restart soul-diagnosis`  

※ 大量ファイルは **rsync の方が早く安全**です。

---

## デプロイ後の確認 URL（パス例）

ドメインやリバースプロキシの設定に合わせて読み替えます。

| パス | 内容 |
|------|------|
| `/` | 10問魂タイプ診断 |
| `/premium/ai-report` | 本格レポート（有料・OpenAI） |
| `/soul-nav` | 魂のナビAI |
| `/shindan-ai/` | 魂のナビ診断AI（5問ウィザード） |

---

## トラブルシューティング

| 現象 | 対処 |
|------|------|
| `Permission denied (publickey)` | 鍵のパス、`HOST` のユーザー名、VPS の `~/.ssh/authorized_keys` を確認 |
| `sudo: a terminal is required` | `ssh` に **`-t`** を付ける（`deploy.sh` は既に対応） |
| 変更が反映されない | 同期先ディレクトリが systemd の `WorkingDirectory` と一致しているか確認 |
| 5分後メールが届かない | `sudo systemctl status soul-diagnosis-followup-worker --no-pager` で worker の稼働確認。未導入ならアクセス時処理のため、無アクセス中は送信されない |
| 本格レポートやナビが書き込めない | VPS 上で `data/premium_reports` と `data/soul_nav_sessions` の存在と、プロセスユーザーの書き込み権限を確認 |
| `/soul-nav/turn` が **500**（アドレスバー直打ち） | `/turn` は **フォーム送信（POST）専用**です。開くのは **`/soul-nav`**。最新コードでは GET は `/soul-nav` へリダイレクトします。 |
| ナビ送信後に **500**（保存失敗） | gunicorn 実行ユーザーが `data/soul_nav_sessions` に書けるか確認。例: `sudo chown -R ubuntu:ubuntu ~/apps/soul-diagnosis/data`（実ユーザーは `systemctl cat soul-diagnosis` の `User=` に合わせる） |
| Import エラー | サーバーで `pip install -r requirements.txt`、新ファイル `premium_report.py` が同期されているか確認 |
| Chrome で **`NET::ERR_CERT_COMMON_NAME_INVALID`**（接続はプライバシーで保護されません） | **証明書のドメインとアクセス中のホスト名が不一致**。例: `https://tamashiinavi.com` なのに Nginx が別名用の `ssl_certificate` を返している。該当 `server { server_name ...; }` と `ssl_certificate` のパスを **`tamashiinavi.com` 用に揃える**。Let’s Encrypt 未取得なら下記で取得後 `nginx -t` → `reload`。 |

**証明書の取り直し例（`tamashiinavi.com`・Nginx あり）:**

```bash
sudo certbot certonly --nginx -d tamashiinavi.com -d www.tamashiinavi.com
```

取得後、サイト設定の `ssl_certificate` / `ssl_certificate_key` を  
`/etc/letsencrypt/live/tamashiinavi.com/` 配下に合わせる。  
**デフォルトサーバ**（`server_name _` など）が 443 で先にマッチし、別ドメインの証明書を返していないかも確認する。

---

## VPS を消したあとの復旧（複数ドメイン）

同一アプリで **gaiaarts.org**（英語トップ）・**魂のナビ用ドメイン**（`/` → `/navi`）・**life-energy-coaching.net**（`/lec` 相当のトップ）を載せる場合の目安です。

| ドメイン例 | アプリの挙動（`Host` ヘッダ） |
|------------|------------------------------|
| `gaiaarts.org` / `www` | `/` が英語ランディング（`en_landing.html`） |
| `life-energy-coaching.net` / `www` | `/` が LEC ランディング（`lec_landing.html`）。別名は `.env` の `LIFE_ENERGY_ROOT_HOSTS`（カンマ区切り）で指定可 |
| 上記以外（例: 魂のナビ本番ドメイン） | `/` が 308 で `/navi`（日本語無料診断LP）へ |

1. **初回**: 上記「前提条件」の `mkdir`・`venv`・`pip install -r requirements.txt`・`data/` 作成  
2. **systemd**: リポジトリの `server/soul-diagnosis.service.example` を `/etc/systemd/system/soul-diagnosis.service` にコピーし、`User`・`WorkingDirectory`・`ExecStart` のパスを VPS に合わせて編集  
3. **Nginx**: `server/nginx-multi-domain.conf.example` を参考に、`server_name` と SSL パスを実ドメインに合わせて `sites-available` に配置 → `nginx -t` → `reload`  
4. **SSL**: 例 `sudo certbot certonly --nginx -d example.com -d www.example.com`（ドメインごと）  
5. **コード反映**: Mac から `./deploy.sh`（`deploy.sh` の `HOST` を実サーバーに合わせる）

---

## セキュリティの注意

- **`.env` を Git に含めない**（既に `.gitignore` 想定）  
- **`PREMIUM_ACCESS_CODE` は推測されにくい値にする**  
- 本番では **`ALLOW_PREMIUM_DEMO=1` を使わない**  
