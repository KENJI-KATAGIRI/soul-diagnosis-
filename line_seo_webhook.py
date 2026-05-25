"""
LINE SEO Webhook Blueprint
LINEから「SEO実行」「それお願い」などのメッセージでSEO改善を操作できる
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import subprocess
import threading
import urllib.request
from datetime import date
from pathlib import Path

from flask import Blueprint, abort, request

# ── 設定 ─────────────────────────────────────────────────
SECRETS = Path("/home/ubuntu/.secrets")
SEO_DIR = Path("/home/ubuntu/apps/seo-improver")
PYTHON  = SEO_DIR / ".venv/bin/python"

def _read(p: Path, default: str = "") -> str:
    return p.read_text().strip() if p.exists() else default

LINE_TOKEN      = _read(SECRETS / "line_seo_token.txt")
LINE_SECRET     = _read(SECRETS / "line_seo_secret.txt")
OWNER_LINE_ID   = _read(SECRETS / "owner_line_id.txt")

FLAG_PENDING = Path("/tmp/seo_pending_apply.flag")
FLAG_RUNNING = Path("/tmp/seo_running.flag")

line_seo_bp = Blueprint("line_seo", __name__)

# ── LINE API ──────────────────────────────────────────────
def _line_api(endpoint: str, payload: dict) -> bool:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.line.me/v2/bot/message/{endpoint}",
        data=data,
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception:
        return False

def push(user_id: str, text: str) -> bool:
    chunks = [text[i:i+4900] for i in range(0, len(text), 4900)]
    messages = [{"type": "text", "text": c} for c in chunks]
    for i in range(0, len(messages), 5):
        _line_api("push", {"to": user_id, "messages": messages[i:i+5]})
    return True

def reply(reply_token: str, text: str) -> bool:
    return _line_api("reply", {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
    })

# ── 提案フォーマット ──────────────────────────────────────
def format_proposal(proposal: dict) -> str:
    lines = [f"📊 SEO改善提案 ({proposal['date']})\n"]
    for site_key, sd in proposal.get("sites", {}).items():
        label   = sd.get("label", site_key)
        changes = sd.get("changes", [])
        gsc     = sd.get("gsc_summary", {})
        clicks  = gsc.get("clicks", "－")
        impr    = gsc.get("impressions", "－")
        lines.append(f"【{label}】")
        lines.append(f"  clicks:{clicks} / 表示:{impr}")
        if changes:
            for i, c in enumerate(changes, 1):
                desc = (c.get("description") or "")[:60]
                lines.append(f"  {i}. {desc}")
        else:
            lines.append("  変更なし")
        lines.append("")
    lines.append("──────────────")
    lines.append("「それお願い」と返信すると全サイトに適用します。")
    return "\n".join(lines)

# ── 履歴フォーマット ──────────────────────────────────────
def format_history() -> str:
    proposals_dir = SEO_DIR / "proposals"
    files = sorted(proposals_dir.glob("*.json"), reverse=True)[:5]
    if not files:
        return "履歴がありません。"
    lines = ["📋 SEO改善履歴（直近5回）\n"]
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            date_str = d.get("date", f.stem)
            lines.append(f"■ {date_str}")
            for site_key, sd in d.get("sites", {}).items():
                label = sd.get("label", site_key)
                changes = sd.get("changes", [])
                if changes:
                    lines.append(f"  【{label}】 {len(changes)}件")
                    for c in changes[:3]:
                        desc = (c.get("description") or "")[:50]
                        lines.append(f"    ・{desc}")
                    if len(changes) > 3:
                        lines.append(f"    ...他{len(changes)-3}件")
            lines.append("")
        except Exception:
            continue
    return "\n".join(lines)

# ── バックグラウンドタスク ────────────────────────────────
def _run_propose(user_id: str):
    FLAG_RUNNING.write_text("propose")
    try:
        subprocess.run(
            [str(PYTHON), str(SEO_DIR / "seo_improver.py")],
            cwd=str(SEO_DIR), timeout=900,
        )
        today = date.today().isoformat()
        proposal_path = SEO_DIR / "proposals" / f"{today}.json"
        if proposal_path.exists():
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            FLAG_PENDING.write_text(today)
            push(user_id, format_proposal(proposal))
        else:
            push(user_id, "⚠️ 提案ファイルが見つかりませんでした。ログを確認してください。")
    except subprocess.TimeoutExpired:
        push(user_id, "⏰ タイムアウト（15分）しました。ログを確認してください。")
    except Exception as e:
        push(user_id, f"❌ エラー: {str(e)[:200]}")
    finally:
        FLAG_RUNNING.unlink(missing_ok=True)

def _run_apply(user_id: str, date_str: str):
    FLAG_RUNNING.write_text("apply")
    try:
        subprocess.run(
            [str(PYTHON), str(SEO_DIR / "seo_improver.py"), "--apply", date_str],
            cwd=str(SEO_DIR), timeout=300,
        )
        FLAG_PENDING.unlink(missing_ok=True)
    except subprocess.TimeoutExpired:
        push(user_id, "⏰ 適用タイムアウトしました。")
    except Exception as e:
        push(user_id, f"❌ 適用エラー: {str(e)[:200]}")
    finally:
        FLAG_RUNNING.unlink(missing_ok=True)

# ── Webhook エンドポイント ────────────────────────────────
@line_seo_bp.route("/line-seo-webhook", methods=["POST"])
def webhook():
    body = request.get_data(as_text=True)

    if LINE_SECRET:
        sig = request.headers.get("X-Line-Signature", "")
        digest = hmac.new(LINE_SECRET.encode(), body.encode(), hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        if not hmac.compare_digest(sig, expected):
            abort(400)

    data = json.loads(body)
    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        user_id     = event["source"].get("userId", "")
        text        = event["message"]["text"].strip()
        reply_token = event.get("replyToken", "")

        # 全ユーザーIDをログ（デバッグ用）
        Path("/tmp/line_seo_last_user.txt").write_text(
            f"user_id={user_id}\ntext={text}\nowner={OWNER_LINE_ID}\nmatch={user_id == OWNER_LINE_ID}"
        )

        if OWNER_LINE_ID and user_id != OWNER_LINE_ID:
            continue

        if "SEO実行" in text:
            if FLAG_RUNNING.exists():
                reply(reply_token, "⏳ すでに実行中です。完了までお待ちください。")
            else:
                reply(reply_token,
                      "🔍 SEO分析を開始します！\n"
                      "4サイトのデータ取得＋AI改善案生成中...\n"
                      "（5〜10分かかります。終わったら改善案を送ります）")
                threading.Thread(target=_run_propose, args=(user_id,), daemon=True).start()

        elif any(kw in text for kw in ["それお願い", "実行して", "適用して", "apply"]):
            if FLAG_RUNNING.exists():
                reply(reply_token, "⏳ すでに実行中です。")
            elif FLAG_PENDING.exists():
                date_str = FLAG_PENDING.read_text().strip()
                reply(reply_token, f"✅ {date_str}の改善案を全サイトに適用します！\n完了したらお知らせします。")
                threading.Thread(target=_run_apply, args=(user_id, date_str), daemon=True).start()
            else:
                # cronで自動生成された提案（FLAG_PENDINGなし）にもフォールバック
                candidates = sorted((SEO_DIR / "proposals").glob("*.json"), reverse=True)
                if candidates:
                    date_str = candidates[0].stem
                    reply(reply_token, f"✅ {date_str}の改善案を全サイトに適用します！\n完了したらお知らせします。")
                    threading.Thread(target=_run_apply, args=(user_id, date_str), daemon=True).start()
                else:
                    reply(reply_token, "⚠️ 適用できる提案がありません。\n先に「SEO実行」と送ってください。")

        elif "SEO状況" in text or "状況確認" in text:
            logs = sorted((SEO_DIR / "logs").glob("seo_*.log"))
            if logs:
                tail = logs[-1].read_text(encoding="utf-8")[-600:]
                reply(reply_token, f"📋 最終ログ:\n{tail}")
            else:
                reply(reply_token, "ログが見つかりません。")

        elif "SEO履歴" in text or "履歴確認" in text:
            reply(reply_token, format_history())

        elif "SEOヘルプ" in text or "help" in text.lower():
            reply(reply_token,
                  "📖 SEOコマンド一覧\n\n"
                  "「SEO実行」→ 4サイトの改善案を生成してLINEに送信\n"
                  "「それお願い」→ 最新の改善案を全サイトに適用\n"
                  "「SEO状況」→ 最終実行のログを表示\n"
                  "「SEO履歴」→ 過去の改善内容を表示\n"
                  "「SEOヘルプ」→ この一覧を表示")

        else:
            reply(reply_token, "📖 コマンドが認識できませんでした。\n「SEOヘルプ」と送ると一覧が見られます。")

    return "OK"

@line_seo_bp.route("/line-seo-debug", methods=["GET"])
def debug_last_user():
    log = Path("/tmp/line_seo_last_user.txt")
    return log.read_text() if log.exists() else "no data yet"
