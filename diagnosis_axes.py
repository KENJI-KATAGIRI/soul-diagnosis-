"""
魂タイプ診断の補助軸（講座理論 soul_navigation_theory.md に準拠）。

- 変容フェーズ: 揺れ / 崩壊・再編 / 空白 / 統合
- ナビの寄り: 心のナビ（安全・評価） vs 魂のナビ（体感・一致）
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

PHASE_KEYS: Tuple[str, ...] = ("phase_sway", "phase_collapse", "phase_void", "phase_integration")
NAVI_KEYS: Tuple[str, ...] = ("navi_mind", "navi_soul")

PHASE_COPY: Dict[str, Tuple[str, str]] = {
    "phase_sway": (
        "揺れ期",
        "前は合っていた基準が、急に重く感じることが増えている段階です。"
        "迷いは故障ではなく、地図の切り替えの合図として扱うと整えやすくなります。",
    ),
    "phase_collapse": (
        "崩壊・再編期",
        "価値観・役割・関係性など、これまでの「器」が手放しや再編を求めている段階です。"
        "罰ではなく、次の一貫性のための解体として見立てられます。",
    ),
    "phase_void": (
        "空白期",
        "何も決めたくない・情報に疲れるなど、一時的な空白を伴いやすい段階です。"
        "停滞ではなく、魂側の再設計が進む時間帯として扱うと負担が減ります。",
    ),
    "phase_integration": (
        "統合・加速期",
        "ズレたまま進むことへの拒否感が強まり、一致を基準に戻したい欲求が出やすい段階です。"
        "スピードより、抵抗の少ない動き方への関心が高まります。",
    ),
}


def score_diagnosis(
    answers: Dict[str, int],
    questions: List[Any],
    soul_type_keys: Tuple[str, ...],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int]]:
    """魂タイプ・フェーズ・ナビの生スコアを同時計算。"""
    soul: Dict[str, int] = {k: 0 for k in soul_type_keys}
    phase: Dict[str, int] = {k: 0 for k in PHASE_KEYS}
    navi: Dict[str, int] = {k: 0 for k in NAVI_KEYS}

    for q in questions:
        a = answers.get(q.key, 3)
        try:
            a = int(a)
        except (TypeError, ValueError):
            a = 3
        if a not in {1, 2, 3, 4, 5}:
            a = 3
        intensity = a - 3
        weights = getattr(q, "axis_weights", None) or {}
        for axis, w in weights.items():
            if axis in soul:
                soul[axis] += int(w) * intensity
            elif axis in phase:
                phase[axis] += int(w) * intensity
            elif axis in navi:
                navi[axis] += int(w) * intensity

    min_soul = min(soul.values()) if soul else 0
    if min_soul < 0:
        off = -min_soul
        soul = {k: v + off for k, v in soul.items()}

    return soul, phase, navi


def pick_secondary_type(soul_scores: Dict[str, int], best_key: str, priority: List[str]) -> str:
    items = [(k, soul_scores.get(k, 0)) for k in priority if k != best_key]
    if not items:
        return ""
    best = max(items, key=lambda kv: (kv[1], -priority.index(kv[0])))
    return best[0]


def build_position_profile(
    *,
    phase_scores: Dict[str, int],
    navi_scores: Dict[str, int],
    soul_scores: Dict[str, int],
    best_key: str,
    soul_types: Dict[str, Any],
    type_priority: List[str],
) -> Dict[str, str]:
    """結果ページ用の「現在地」テキストを組み立てる。"""

    # フェーズ: 最高得点（同点は priority 順）
    phase_order = list(PHASE_KEYS)
    best_phase = max(phase_scores.items(), key=lambda kv: (kv[1], -phase_order.index(kv[0])))[0]
    phase_title, phase_body = PHASE_COPY.get(best_phase, ("", ""))

    # ナビ寄り
    mind = int(navi_scores.get("navi_mind", 0))
    soul_n = int(navi_scores.get("navi_soul", 0))
    diff = mind - soul_n
    if diff >= 3:
        navi_title = "心のナビ寄り（安全・評価が先に立ちやすい）"
        navi_body = (
            "判断の前に「損しないか」「間違えないか」「どう見られるか」が先に浮かびやすい傾向です。"
            "講座理論では、正しさで整った地図がまだ強く効いている状態に近いです。"
        )
    elif diff <= -3:
        navi_title = "魂のナビ寄り（体感・一致を重視しやすい）"
        navi_body = (
            "言葉の正しさより、胸の緩みや呼吸、翌日も残る感覚を手がかりにしたい傾向です。"
            "ズレると体が先に反応しやすい段階かもしれません。"
        )
    else:
        navi_title = "心と魂のナビが混在しやすい"
        navi_body = (
            "状況によって、安全基準と体感基準が交互に強く出やすい状態です。"
            "講座では「アクセルとブレーキ同時踏み」に近い揺れとして扱います。"
        )

    sub_key = pick_secondary_type(soul_scores, best_key, type_priority)
    sub_name = soul_types[sub_key].name if sub_key and sub_key in soul_types else ""

    return {
        "phase_key": best_phase,
        "phase_title": phase_title,
        "phase_body": phase_body,
        "navi_title": navi_title,
        "navi_body": navi_body,
        "sub_type_name": sub_name,
    }
