from __future__ import annotations

from enum import Enum

from soul_nav_ai.diagnosis import DiagnosisResult


class YesNoLean(str, Enum):
    YES = "yes"
    NO = "no"
    MIXED = "mixed"
    UNCLEAR = "unclear"


def lean_from_diagnosis(d: DiagnosisResult) -> YesNoLean:
    """ルールベースのYES/NO寄りのたたき台（モデルはこれを超えて身体感覚で再評価する）。"""
    o = len(d.obligation_hits)
    y = len(d.desire_fear_hits)
    if o == 0 and y == 0:
        return YesNoLean.UNCLEAR
    if o > 0 and y > 0:
        return YesNoLean.MIXED
    if o > y:
        return YesNoLean.NO
    return YesNoLean.YES


def lean_label_ja(lean: YesNoLean) -> str:
    return {
        YesNoLean.YES: "YES寄り（軽さ・拡張・自然さの手がかり）",
        YesNoLean.NO: "NO寄り（重さ・義務・違和の手がかり）",
        YesNoLean.MIXED: "混在（表面と本音のズレの可能性）",
        YesNoLean.UNCLEAR: "シグナル弱め（身体感覚の確認が必要）",
    }[lean]
