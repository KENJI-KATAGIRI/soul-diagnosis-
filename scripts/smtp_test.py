#!/usr/bin/env python3
"""
さくら SMTP 経由のテスト送信。.env の SMTP_* を読み込みます。

  cd プロジェクトルート
  python3 scripts/smtp_test.py

宛先: 環境変数 SMTP_TEST_TO（未設定時は SMTP_FROM_EMAIL＝自分宛テスト）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_ENV_PATH = ROOT / ".env"


def _load_env_fallback() -> None:
    """python-dotenv なしでも .env を読む（KEY=VALUE のみ）。"""
    if not _ENV_PATH.is_file():
        return
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            os.environ[k] = v


try:
    from dotenv import load_dotenv

    load_dotenv(_ENV_PATH, override=True)
except Exception:
    _load_env_fallback()

from email.message import EmailMessage
import smtplib


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return raw.strip() == "1"


def main() -> int:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587").strip() or "587")
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    from_name = os.environ.get("SMTP_FROM_NAME", "").strip() or "魂のナビ診断"
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    reply_to = os.environ.get("SMTP_REPLY_TO", "").strip()
    to_email = os.environ.get("SMTP_TEST_TO", "").strip() or from_email

    if not host or not from_email:
        print("ERROR: SMTP_HOST または SMTP_FROM_EMAIL が未設定です。", file=sys.stderr)
        return 1
    if not user or not password:
        print("ERROR: SMTP_USER または SMTP_PASS が未設定です。", file=sys.stderr)
        return 1
    if not to_email:
        print("ERROR: 宛先がありません。SMTP_TEST_TO または SMTP_FROM_EMAIL を設定してください。", file=sys.stderr)
        return 1

    subject = os.environ.get("SMTP_TEST_SUBJECT", "").strip() or "【魂のナビ診断】SMTPテスト"
    body = (
        "これは魂のナビ診断アプリからの SMTP テストメールです。\n\n"
        f"SMTP_HOST={host}\n"
        f"SMTP_PORT={port}\n"
        "送信に成功していれば、さくらメールサーバー経由の設定は有効です。\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    use_ssl = _bool("SMTP_USE_SSL", False)
    use_starttls = _bool("SMTP_USE_STARTTLS", True)
    timeout = float(os.environ.get("SMTP_TIMEOUT_SEC", "30").strip() or "30")

    print(f"Connecting {host}:{port} (SSL={use_ssl}, STARTTLS={use_starttls})...")
    print(f"From: {from_email}  To: {to_email}")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls()
                    server.ehlo()
                server.login(user, password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        print(f"ERROR: Authentication failed — SMTP_USER / SMTP_PASS を確認してください。\n{e}", file=sys.stderr)
        return 2
    except ConnectionRefusedError as e:
        print(f"ERROR: Connection refused — ホスト名・ポート（587/465）を確認してください。\n{e}", file=sys.stderr)
        return 3
    except smtplib.SMTPException as e:
        print(f"ERROR: SMTP — {type(e).__name__}: {e}", file=sys.stderr)
        return 4
    except OSError as e:
        print(f"ERROR: Network — {type(e).__name__}: {e}", file=sys.stderr)
        return 5

    print("OK: メール送信に成功しました。受信トレイ（および迷惑メール）を確認してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
