from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from lib.diagnosis_email import is_diagnosis_result_email_enabled, send_diagnosis_result_email
from lib.followup_email import is_followup_email_enabled, send_followup_email

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> Optional[datetime]:
    raw = (s or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _data_dir() -> Path:
    root = Path(__file__).resolve().parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _queue_path() -> Path:
    return _data_dir() / "followup_queue.json"


def _state_path() -> Path:
    return _data_dir() / "followup_state.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def mark_state(email: str, key: str, value: bool = True) -> None:
    mail = (email or "").strip().lower()
    if not mail:
        return
    state = _load_json(_state_path(), {})
    if not isinstance(state, dict):
        state = {}
    box = state.get(mail)
    if not isinstance(box, dict):
        box = {}
    box[key] = value
    state[mail] = box
    _save_json(_state_path(), state)


def has_state(email: str, key: str) -> bool:
    mail = (email or "").strip().lower()
    if not mail:
        return False
    state = _load_json(_state_path(), {})
    if not isinstance(state, dict):
        return False
    box = state.get(mail)
    if not isinstance(box, dict):
        return False
    return bool(box.get(key))


def enqueue_followup(
    *,
    email: str,
    name: str,
    kind: str,
    context: Dict[str, Any],
    delay_minutes: int,
    dedupe_key: str,
) -> bool:
    mail = (email or "").strip().lower()
    if not mail:
        return False
    queue = _load_json(_queue_path(), [])
    if not isinstance(queue, list):
        queue = []
    for item in queue:
        if isinstance(item, dict) and item.get("email") == mail and item.get("dedupe_key") == dedupe_key:
            return False
    due_at = _utc_now() + timedelta(minutes=max(0, delay_minutes))
    queue.append(
        {
            "email": mail,
            "name": (name or "").strip(),
            "kind": kind,
            "context": context,
            "due_at": _iso(due_at),
            "dedupe_key": dedupe_key,
            "status": "pending",
        }
    )
    _save_json(_queue_path(), queue)
    return True


def _build_message(kind: str, context: Dict[str, Any]) -> Tuple[str, str]:
    course_url = str(context.get("course_url") or "").strip()
    premium_url = str(context.get("premium_url") or "").strip()
    ai_url = str(context.get("ai_url") or "").strip()
    type_name = str(context.get("type_name") or "あなたのタイプ")

    if kind == "result_no_course":
        subject = "結果を見た後、止まりやすいポイントをお送りします"
        body = (
            f"{type_name}の結果を見た方が、次に止まりやすいポイントを共有します。\n\n"
            "理解だけで終わると、日常では元の判断パターンに戻りやすくなります。\n"
            "講座ページで「整え方」を先に確認しておくと、迷いの戻りを減らせます。\n\n"
            f"講座詳細を見る: {course_url}\n"
        )
        return subject, body

    if kind == "course_no_apply":
        subject = "講座を検討中の方へ｜申込前に確認してほしいこと"
        body = (
            "申込前に不安が残るのは自然です。\n"
            "向いている人/向いていない人、申込後の流れをもう一度確認してください。\n\n"
            f"講座詳細: {course_url}\n"
            f"まだ迷う場合のAI統合診断: {ai_url}\n"
        )
        return subject, body

    if kind == "premium_buyer_to_course":
        subject = "本格レポートの次に、変化を定着させる方法"
        body = (
            "レポートで構造理解が進んだ方ほど、次は実践設計が重要になります。\n"
            "選択軸の整え方は、講座の実践パートで定着しやすくなります。\n\n"
            f"講座詳細: {course_url}\n"
        )
        return subject, body

    if kind == "ai_buyer_to_course":
        subject = "統合診断の気づきを現実変化につなげる次の一歩"
        body = (
            "統合診断で見えた課題を、日常の判断へ落とし込むフェーズです。\n"
            "実践環境があると、変化の再現性が上がります。\n\n"
            f"講座詳細: {course_url}\n"
        )
        return subject, body

    subject = "診断後のご案内"
    body = (
        "続きのご案内です。\n"
        f"講座詳細: {course_url}\n"
        f"本格レポート: {premium_url}\n"
        f"AI統合診断: {ai_url}\n"
    )
    return subject, body


def process_pending_followups(max_items: int = 2) -> int:
    if not is_followup_email_enabled() and not is_diagnosis_result_email_enabled():
        return 0
    queue = _load_json(_queue_path(), [])
    if not isinstance(queue, list) or not queue:
        return 0

    now = _utc_now()
    sent = 0
    changed = False
    for item in queue:
        if sent >= max_items:
            break
        if not isinstance(item, dict):
            continue
        if item.get("status") != "pending":
            continue
        due = _parse_iso(str(item.get("due_at") or ""))
        if due is None:
            # 以前の実装ではパース失敗時に due=now となり即送信されていた
            logger.warning(
                "followup_queue: missing or invalid due_at (skip send): email=%s kind=%s due_at=%r",
                item.get("email"),
                item.get("kind"),
                item.get("due_at"),
            )
            item["status"] = "failed"
            item["result"] = "invalid or missing due_at"
            changed = True
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        else:
            due = due.astimezone(timezone.utc)
        if due > now:
            continue

        email = str(item.get("email") or "").strip().lower()
        kind = str(item.get("kind") or "")
        if not email:
            item["status"] = "failed"
            changed = True
            continue

        if kind == "course_no_apply" and has_state(email, "course_apply_clicked"):
            item["status"] = "cancelled"
            changed = True
            continue
        if kind == "result_no_course" and has_state(email, "course_lp_viewed"):
            item["status"] = "cancelled"
            changed = True
            continue

        context = item.get("context") if isinstance(item.get("context"), dict) else {}
        if kind == "diagnosis_result_email":
            ok, detail = send_diagnosis_result_email(
                to_email=email,
                to_name=str(item.get("name") or ""),
                payload=context,
            )
        else:
            subject, body = _build_message(kind, context)
            ok, detail = send_followup_email(
                to_email=email,
                to_name=str(item.get("name") or ""),
                subject=subject,
                body=body,
            )
        item["status"] = "sent" if ok else "failed"
        item["result"] = detail
        item["sent_at"] = _iso(now)
        sent += 1 if ok else 0
        changed = True

    if changed:
        _save_json(_queue_path(), queue)
    return sent
