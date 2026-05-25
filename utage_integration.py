"""
UTAGE（または汎用Webhook）へ診断付きリードをPOSTする。
標準ライブラリのみ（urllib）。
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
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROBLEM_CATEGORY_BY_TYPE: Dict[str, str] = {
    "intuition_navi": "direction_clarity",
    "strategy_thinker": "decision_overload",
    "action_breakthrough": "effort_mismatch",
    "harmony_leader": "boundary_clarity",
}

_UTAGE_FORM_RID_RE = re.compile(r'name=["\']rid["\']\s+value=["\']([^"\']+)["\']', re.IGNORECASE)
_RID_CACHE: Dict[str, str] = {}


def _normalize_energy_score(scores_by_key: Dict[str, int]) -> int:
    """スコアをざっくり 0〜100 に正規化（同一セッション内の相対値）。"""
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


def _apply_field_aliases(payload: Dict[str, Any]) -> Dict[str, Any]:
    """環境変数 UTAGE_FIELD_* でキーを上書き（値は同じ）。"""
    out = dict(payload)
    for k in list(out.keys()):
        alias = os.environ.get(f"UTAGE_FIELD_{k.upper()}", "").strip()
        if alias and alias != k:
            out[alias] = out.pop(k)
    return out


def _utage_send_format(url: str) -> str:
    raw = os.environ.get("UTAGE_SEND_FORMAT", "").strip().lower()
    if raw in {"json", "form"}:
        return raw
    path = urlsplit(url).path.lower()
    if path.endswith("/register") or path.endswith("/store"):
        return "form"
    return "json"


def _replace_path_suffix(url: str, old: str, new: str) -> str:
    parts = urlsplit(url)
    if not parts.path.lower().endswith(old):
        return url
    new_path = parts.path[: -len(old)] + new
    return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, ""))


def _form_register_url(url: str) -> str:
    if urlsplit(url).path.lower().endswith("/store"):
        return _replace_path_suffix(url, "/store", "/register")
    return url


def _form_post_url(url: str) -> str:
    if urlsplit(url).path.lower().endswith("/register"):
        return _replace_path_suffix(url, "/register", "/store")
    return url


def _resolve_form_rid(url: str, timeout: float) -> Optional[str]:
    rid = os.environ.get("UTAGE_FORM_RID", "").strip()
    if rid:
        return rid

    register_url = _form_register_url(url)
    cached = _RID_CACHE.get(register_url)
    if cached:
        return cached

    req = Request(register_url, headers={"User-Agent": "soul-diagnosis-utage/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    match = _UTAGE_FORM_RID_RE.search(html)
    if not match:
        return None
    rid = match.group(1).strip()
    if rid:
        _RID_CACHE[register_url] = rid
    return rid


def _build_form_payload(payload: Dict[str, Any], rid: str) -> Dict[str, str]:
    out = _apply_field_aliases(payload)
    email_value = str(payload.get("email", "")).strip().lower()
    email_field = os.environ.get("UTAGE_FORM_EMAIL_FIELD", "").strip() or "mail"
    if email_value and email_field not in out:
        out[email_field] = email_value
    out["rid"] = rid
    return {k: str(v) for k, v in out.items() if v is not None and str(v).strip() != ""}


def post_utage_lead(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """
    UTAGE_LEAD_URL へ POST。
    Webhook は JSON、UTAGE の register/store フォームは form-urlencoded を使う。
    戻り値: (成功?, メッセージまたはエラー要約)
    """
    url = os.environ.get("UTAGE_LEAD_URL", "").strip()
    if not url:
        return False, "UTAGE_LEAD_URL is not set"

    send_format = _utage_send_format(url)
    timeout = float(os.environ.get("UTAGE_TIMEOUT_SEC", "12") or "12")
    target_url = url
    headers = {
        "User-Agent": "soul-diagnosis-utage/1.0",
    }
    token = os.environ.get("UTAGE_WEBHOOK_SECRET", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    extra_h = os.environ.get("UTAGE_HEADER_EXTRA", "").strip()
    if extra_h and ":" in extra_h:
        hk, _, hv = extra_h.partition(":")
        headers[hk.strip()] = hv.strip()

    if send_format == "form":
        rid = _resolve_form_rid(url, timeout)
        if not rid:
            return False, "UTAGE form rid is missing; set UTAGE_FORM_RID or use the register URL"
        target_url = _form_post_url(url)
        body = urlencode(_build_form_payload(payload, rid), doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
    else:
        body = json.dumps(_apply_field_aliases(payload), ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    req = Request(target_url, data=body, headers=headers, method="POST")

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
