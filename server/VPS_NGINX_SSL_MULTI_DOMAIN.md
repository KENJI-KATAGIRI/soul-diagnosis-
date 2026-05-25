# Ubuntu VPS：nginx ＋ 3ドメイン ＋ Let’s Encrypt（初心者向け）

同一VPSで次の3ドメインを静的サイトとして動かす手順です。

- `life-energy-coaching.net`（`www` 付き含む）
- `gaiaarts.org`（`www` 付き含む）
- `tamashiinavi.com`（`www` 付き含む）

**前提**

- DNS の **A レコード（`@` と `www`）がすべてこの VPS のグローバルIP** を向いている
- **root でログインしているか、`sudo` が使える**ユーザーで作業する
- **HTTP→HTTPS のみ**リダイレクトし、**`www` と非 `www` の間ではリダイレクトしない**（`https://$host$request_uri` でホストを維持）。SEOの正規URLはアプリ側の `canonical` で非wwwに揃える

> **注意（本リポジトリの Flask 本番との関係）**  
> 魂のナビ講座の本番は **Gunicorn ＋ nginx の `proxy_pass`**（`nginx-multi-domain.conf.example`）です。  
> ここで作る **`/var/www/...` の静的構成は「テスト用・別用途」**です。同じVPSでFlaskと共存させる場合は、`root` の代わりに `proxy_pass http://127.0.0.1:8000;` に差し替えるなど **設定を統合**してください。

---

## 0. 変数の準備（コピペ用）

```bash
# VPS のパブリックIP（確認用）
curl -4 -s ifconfig.me && echo
```

---

## ① UFW：80 / 443 を開放

| やること | ファイアウォールで HTTP/HTTPS を許可する |
| コマンド | 下記 |
| 確認 | `sudo ufw status` で `80/tcp` `443/tcp` が `ALLOW` |

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status verbose
```

**よくあるエラー**

- SSH 切れ：**必ず `OpenSSH` を先に許可**してから `enable` すること

---

## ② nginx インストール

| やること | nginx を入れる |
| コマンド | 下記 |
| 確認 | `nginx -v` と `systemctl status nginx` |

```bash
sudo apt update
sudo apt install -y nginx
nginx -v
sudo systemctl enable nginx
sudo systemctl start nginx
sudo systemctl status nginx --no-pager
```

---

## ③ ディレクトリ作成 ＋ 権限

| やること | 各ドメイン用のドキュメントルートを作る |
| コマンド | 下記 |
| 確認 | `ls -la /var/www` |

```bash
sudo mkdir -p /var/www/life-energy-coaching.net/html
sudo mkdir -p /var/www/gaiaarts.org/html
sudo mkdir -p /var/www/tamashiinavi.com/html

sudo chown -R www-data:www-data /var/www/life-energy-coaching.net
sudo chown -R www-data:www-data /var/www/gaiaarts.org
sudo chown -R www-data:www-data /var/www/tamashiinavi.com
```

---

## ④ 各ディレクトリに `index.html`（テスト用）

| やること | ドメイン名が分かるテストページを置く |
| コマンド | 下記（3つ） |
| 確認 | `curl -s http://127.0.0.1/` は default サイトのままなので、⑤の後に各 `server_name` で確認 |

**life-energy-coaching.net**

```bash
sudo tee /var/www/life-energy-coaching.net/html/index.html > /dev/null <<'EOF'
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>life-energy-coaching.net</title></head>
<body><h1>OK: life-energy-coaching.net</h1><p>静的テストページです。</p></body>
</html>
EOF
```

**gaiaarts.org**

```bash
sudo tee /var/www/gaiaarts.org/html/index.html > /dev/null <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>gaiaarts.org</title></head>
<body><h1>OK: gaiaarts.org</h1><p>Static test page.</p></body>
</html>
EOF
```

**tamashiinavi.com**

```bash
sudo tee /var/www/tamashiinavi.com/html/index.html > /dev/null <<'EOF'
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>tamashiinavi.com</title></head>
<body><h1>OK: tamashiinavi.com</h1><p>静的テストページです。</p></body>
</html>
EOF
```

---

## ⑤ nginx：ドメインごとの設定ファイル（初回は HTTP のみ）

**証明書がまだない段階**では、**ポート80でリダイレクトしない**（Let’s Encrypt の HTTP-01 検証のため）。

以下を **そのまま** `/etc/nginx/sites-available/` に作成します。

```bash
sudo tee /etc/nginx/sites-available/life-energy-coaching.net > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name life-energy-coaching.net www.life-energy-coaching.net;

    root /var/www/life-energy-coaching.net/html;
    index index.html;

    location /.well-known/acme-challenge/ {
        root /var/www/life-energy-coaching.net/html;
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

sudo tee /etc/nginx/sites-available/gaiaarts.org > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name gaiaarts.org www.gaiaarts.org;

    root /var/www/gaiaarts.org/html;
    index index.html;

    location /.well-known/acme-challenge/ {
        root /var/www/gaiaarts.org/html;
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

sudo tee /etc/nginx/sites-available/tamashiinavi.com > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name tamashiinavi.com www.tamashiinavi.com;

    root /var/www/tamashiinavi.com/html;
    index index.html;

    location /.well-known/acme-challenge/ {
        root /var/www/tamashiinavi.com/html;
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
```

---

## ⑥ `sites-enabled` に有効化 ＋ default 無効化

| やること | シンボリックリンクを張り、デフォルトサイトを無効化 |
| コマンド | 下記 |
| 確認 | `nginx -t` → `reload` |

```bash
sudo rm -f /etc/nginx/sites-enabled/default

sudo ln -sf /etc/nginx/sites-available/life-energy-coaching.net /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/gaiaarts.org /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/tamashiinavi.com /etc/nginx/sites-enabled/

sudo nginx -t
sudo systemctl reload nginx
```

**よくあるエラー**

- `nginx: configuration file ... test failed` → メッセージに書かれた **行番号** を直してから再度 `nginx -t`

---

## ⑦ HTTP で表示確認（VPS 上）

| やること | `Host` ヘッダを付けてローカルから確認 |
| コマンド | 下記 |
| 確認 | 各コマンドで `OK:` が含まれる HTML が返る |

```bash
curl -s http://127.0.0.1/ -H "Host: life-energy-coaching.net" | head -5
curl -s http://127.0.0.1/ -H "Host: www.life-energy-coaching.net" | head -5
curl -s http://127.0.0.1/ -H "Host: gaiaarts.org" | head -5
curl -s http://127.0.0.1/ -H "Host: www.gaiaarts.org" | head -5
curl -s http://127.0.0.1/ -H "Host: tamashiinavi.com" | head -5
curl -s http://127.0.0.1/ -H "Host: www.tamashiinavi.com" | head -5
```

**外から確認**（DNS がVPS向きのあと）:

```bash
curl -s http://life-energy-coaching.net/ | head -3
curl -s http://www.life-energy-coaching.net/ | head -3
```

---

## ⑧ certbot インストール

| やること | Let’s Encrypt クライアントを入れる |
| コマンド | 下記 |
| 確認 | `certbot --version` |

```bash
sudo apt install -y certbot python3-certbot-nginx
certbot --version
```

---

## ⑨ SSL 発行（ドメインごとに 1 回ずつ）

| やること | nginx プラグインで証明書取得 ＋ 443 用設定のたたきを作る |
| コマンド | 下記（メールアドレスは自分のものに変更） |
| 確認 | `/etc/letsencrypt/live/` に各ドメイン名のディレクトリができる |

**共通：利用規約に同意する初回だけ**

```bash
sudo certbot --nginx --agree-tos --register-unsafely-without-email --non-interactive \
  -d life-energy-coaching.net -d www.life-energy-coaching.net
```

> メールを登録したい場合は `--register-unsafely-without-email` の代わりに  
> `-m you@example.com` を付け、`--agree-tos` とセットで使います。

```bash
sudo certbot --nginx --agree-tos --register-unsafely-without-email --non-interactive \
  -d gaiaarts.org -d www.gaiaarts.org

sudo certbot --nginx --agree-tos --register-unsafely-without-email --non-interactive \
  -d tamashiinavi.com -d www.tamashiinavi.com
```

**よくあるエラー**

- **DNS がまだVPSを向いていない** → A レコードを直すまで失敗する  
- **ポート80が閉じている** → UFW とクラウド側セキュリティグループを確認  
- **別サーバが応答している** → `dig +short ドメイン A` で IP がこのVPSか確認  

---

## ⑩ nginx テスト ＋ 再読み込み

```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## ⑪ ⑫ 最終設定：HTTP→HTTPS のみ（`www` と非 `www` の間はリダイレクトしない）

certbot 済みの証明書パスを前提に、**各ドメイン1本の `server`（443）**で `server_name` に **裸ドメインと `www` の両方**を書きます。  
**80番**は `https://$host$request_uri` へ **301**（アクセスしてきたホスト名を維持）。

### life-energy-coaching.net

```bash
sudo tee /etc/nginx/sites-available/life-energy-coaching.net > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name life-energy-coaching.net www.life-energy-coaching.net;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name life-energy-coaching.net www.life-energy-coaching.net;

    ssl_certificate     /etc/letsencrypt/live/life-energy-coaching.net/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/life-energy-coaching.net/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/life-energy-coaching.net/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
```

### gaiaarts.org

```bash
sudo tee /etc/nginx/sites-available/gaiaarts.org > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name gaiaarts.org www.gaiaarts.org;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name gaiaarts.org www.gaiaarts.org;

    ssl_certificate     /etc/letsencrypt/live/gaiaarts.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/gaiaarts.org/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/gaiaarts.org/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
```

### tamashiinavi.com

```bash
sudo tee /etc/nginx/sites-available/tamashiinavi.com > /dev/null <<'EOF'
server {
    listen 80;
    listen [::]:80;
    server_name tamashiinavi.com www.tamashiinavi.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name tamashiinavi.com www.tamashiinavi.com;

    ssl_certificate     /etc/letsencrypt/live/tamashiinavi.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tamashiinavi.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    root /var/www/tamashiinavi.com/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
```

**反映**

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 確認

```bash
curl -sI http://life-energy-coaching.net/      | head -5
curl -sI http://www.life-energy-coaching.net/  | head -5
curl -sI https://life-energy-coaching.net/     | head -8
curl -sI https://www.life-energy-coaching.net/   | head -8
```

- **HTTP** → `301` で **同じホスト名の HTTPS** へ  
- **HTTPS（www / 非www それぞれ）** → **301 なしで `200`**（静的サイトの場合）

---

## 証明書の自動更新（timer）

| やること | certbot の systemd timer が有効か確認 |
| コマンド | 下記 |
| 確認 | `timer` が `active` |

```bash
sudo systemctl status certbot.timer --no-pager
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

**ドライラン（推奨）**

```bash
sudo certbot renew --dry-run
```

---

## ゴール確認リスト

| URL | 期待 |
|-----|------|
| `https://life-energy-coaching.net` | 鍵あり・200 |
| `https://www.life-energy-coaching.net` | 鍵あり・200（**www から非www への 301 は出ない**） |
| `https://gaiaarts.org` / `https://www.gaiaarts.org` | 同上 |
| `https://tamashiinavi.com` / `https://www.tamashiinavi.com` | 同上 |
| `http://...` | 301→**同じホスト名の** `https://...` |

---

## （任意）nginx で `www` を裸ドメインに 301 したい場合

`443` に **`server_name www.example.com;` だけの `server` ブロック**を追加し、`return 301 https://example.com$request_uri;` を書く方法があります。証明書の SAN に `www` が含まれている必要があります。

---

## ローカル（開発マシン）

このリポジトリのテンプレや `app.py` を変更した場合は `python3 app.py` の再起動。`.env` はローカル用を維持。

## 本番（この手順の VPS）

手順はすべてサーバ上で実行。Flask 本番と共存する場合は `nginx-multi-domain.conf.example` と **設定の統合**を検討。`.env` はサーバのみ。

## ブラウザ

キャッシュを消すか強制再読み込み。リダイレクトの挙動は開発者ツールの Network で確認。
