"""
UTAGE フォームエンドポイントへ診断付きリードをPOSTする。
標準ライブラリのみ（urllib）。

UTAGE の REST API（api.utage-system.com）は連絡先作成に対応していないため、
フォーム送信エンドポイント（/r/{rid}/store）を使用する。
UTAGE_API_URL に store URL を、UTAGE_API_KEY に API キーを設定する。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROBLEM_CATEGORY_BY_TYPE: Dict[str, str] = {
    "intuition_navi": "direction_clarity",
    "strategy_thinker": "decision_overload",
    "action_breakthrough": "effort_mismatch",
    "harmony_leader": "boundary_clarity",
}

_DEFAULT_UTAGE_API_URL = "https://utage-system.com/r/TjlcA76tYZoW/store"


def _normalize_energy_score(scores_by_key: Dict[str, int]) -> int:
    if not scores_by_key:
        return 0
    vals = [int(v) for v in scores_by_key.values()]
    mx = max(vals) or 1
    return int(min(100, max(0, round(100 * (sum(vals) / (mx * len(vals)))))))


def _email_ok(addr: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr.strip()))


def build_utage_payload(
    *,
    email: str,
    name: str,
    best_key: str,
    type_label: str,
    scores_by_key: Dict[str, int],
    source: str = "soul_quiz",
) -> Dict[str, Any]:
    return {
        "name": name.strip(),
        "email": email.strip().lower(),
        "diagnosis_type": best_key,
        "diagnosis_type_label": type_label,
        "energy_score": _normalize_energy_score(scores_by_key),
        "problem_category": _PROBLEM_CATEGORY_BY_TYPE.get(best_key, "general"),
        "source": source.strip() or "soul_quiz",
        "scores_json": json.dumps(
            {k: int(v) for k, v in scores_by_key.items()}, ensure_ascii=False
        ),
    }


def post_utage_lead(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    UTAGE_API_URL へフォームデータを POST して連絡先登録する。
    戻り値: (成功?, メッセージまたはエラー要約)
    """
    url = os.environ.get("UTAGE_API_URL", _DEFAULT_UTAGE_API_URL).strip()
    if not url:
        return False, "UTAGE_API_URL is not set"

    rid = os.environ.get("UTAGE_FORM_RID", "").strip()
    if not rid:
        return False, "UTAGE_FORM_RID is not set"

    timeout = float(os.environ.get("UTAGE_TIMEOUT_SEC", "12") or "12")

    email_field = os.environ.get("UTAGE_FORM_EMAIL_FIELD", "mail").strip() or "mail"
    form_data: Dict[str, str] = {
        email_field: str(payload.get("email", "")).strip().lower(),
        "name": str(payload.get("name", "")).strip(),
        "rid": rid,
        "diagnosis_type": str(payload.get("diagnosis_type", "")),
        "diagnosis_type_label": str(payload.get("diagnosis_type_label", "")),
        "energy_score": str(payload.get("energy_score", "")),
        "problem_category": str(payload.get("problem_category", "")),
        "source": str(payload.get("source", "soul_quiz")),
        "scores_json": str(payload.get("scores_json", "")),
    }
    form_data = {k: v for k, v in form_data.items() if v}

    headers: Dict[str, str] = {
        "User-Agent": "soul-diagnosis-utage/1.0",
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
    }
    api_key = os.environ.get("UTAGE_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = urlencode(form_data, doseq=True).encode("utf-8")
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as resp:
            _ = resp.read()
            code = resp.getcode()
            if 200 <= code < 300:
                return True, f"HTTP {code}"
            return False, f"HTTP {code}"
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        msg = f"HTTP {e.code} {e.reason} {err_body}"
        logger.warning("UTAGE HTTP error: %s", msg)
        return False, msg
    except URLError as e:
        msg = str(e.reason if hasattr(e, "reason") else e)
        logger.warning("UTAGE URL error: %s", msg)
        return False, msg
    except Exception as e:
        logger.exception("UTAGE unexpected error")
        return False, str(e)


def append_lead_log(ok: bool, email: str, detail: str) -> None:
    """任意: UTAGE_LEAD_LOG=1 で JSONL を data/ に追記。"""
    if os.environ.get("UTAGE_LEAD_LOG", "").strip() != "1":
        return
    root = Path(__file__).resolve().parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "utage_lead_log.jsonl"
    fp = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]
    line = json.dumps(
        {
            "at": datetime.now(timezone.utc).isoformat(),
            "ok": ok,
            "email_sha256_12": fp,
            "detail": detail[:300],
        },
        ensure_ascii=False,
    )
    path.open("a", encoding="utf-8").write(line + "\n")


def validate_lead_form(email: str, name: str) -> Optional[str]:
    email = (email or "").strip()
    if not email:
        return "メールアドレスを入力してください。"
    if not _email_ok(email):
        return "メールアドレスの形式を確認してください。"
    if len(name) > 120:
        return "お名前が長すぎます。"
    return None
