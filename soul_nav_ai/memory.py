from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from soul_nav_ai.flow import FlowPhase


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_data_dir() -> Path:
    base = os.environ.get("SOUL_NAV_DATA_DIR", "").strip()
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent / "data" / "soul_nav_sessions"


@dataclass
class SessionRecord:
    session_id: str
    created_at: str
    updated_at: str
    flow_phase: str = FlowPhase.INTAKE.value
    # 10問診断から引き継いだ魂タイプ（任意）。JSON に保存。
    soul_type_context: Optional[Dict[str, Any]] = None
    turns: List[Dict[str, Any]] = field(default_factory=list)

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


def new_session() -> SessionRecord:
    now = utc_now_iso()
    return SessionRecord(session_id=str(uuid.uuid4()), created_at=now, updated_at=now, turns=[])


def _session_path(data_dir: Path, session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return data_dir / f"{safe}.json"


def load_session(session_id: str, *, data_dir: Optional[Path] = None) -> Optional[SessionRecord]:
    root = data_dir or default_data_dir()
    path = _session_path(root, session_id)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    fp = str(data.get("flow_phase") or FlowPhase.INTAKE.value)
    if fp not in {p.value for p in FlowPhase}:
        fp = FlowPhase.INTAKE.value
    raw_ctx = data.get("soul_type_context")
    ctx: Optional[Dict[str, Any]]
    if raw_ctx is None or not isinstance(raw_ctx, dict):
        ctx = None
    else:
        ctx = cast(Dict[str, Any], raw_ctx)

    return SessionRecord(
        session_id=str(data["session_id"]),
        created_at=str(data["created_at"]),
        updated_at=str(data["updated_at"]),
        flow_phase=fp,
        soul_type_context=ctx,
        turns=list(data.get("turns", [])),
    )


def save_session(rec: SessionRecord, *, data_dir: Optional[Path] = None) -> Path:
    root = data_dir or default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = _session_path(root, rec.session_id)
    path.write_text(json.dumps(rec.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_turn(
    rec: SessionRecord,
    turn: Dict[str, Any],
    *,
    data_dir: Optional[Path] = None,
) -> SessionRecord:
    rec.turns.append(turn)
    rec.updated_at = utc_now_iso()
    save_session(rec, data_dir=data_dir)
    return rec


def compare_with_previous(rec: SessionRecord) -> Optional[Dict[str, Any]]:
    """直近ターンとその前を比較し、変化の要約用データを返す。"""
    if len(rec.turns) < 2:
        return None
    a, b = rec.turns[-2], rec.turns[-1]
    return {
        "previous_turn_index": a.get("turn_index"),
        "current_turn_index": b.get("turn_index"),
        "lean_change": {
            "from": (a.get("signals") or {}).get("preliminary_lean"),
            "to": (b.get("signals") or {}).get("preliminary_lean"),
        },
        "obligation_count_delta": _count_delta(
            a, b, lambda t: len(((t.get("signals") or {}).get("diagnosis") or {}).get("obligation_hits") or []),
        ),
        "desire_fear_count_delta": _count_delta(
            a, b, lambda t: len(((t.get("signals") or {}).get("diagnosis") or {}).get("desire_fear_hits") or []),
        ),
        "user_input_length_delta": (len((b.get("user_input") or "")) - len((a.get("user_input") or ""))),
    }


def _count_delta(a: Dict[str, Any], b: Dict[str, Any], fn) -> int:
    return int(fn(b)) - int(fn(a))
