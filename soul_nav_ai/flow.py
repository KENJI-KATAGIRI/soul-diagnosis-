from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class FlowPhase(str, Enum):
    INTAKE = "intake"
    MIRROR = "mirror"
    YESNO_PROBE = "yesno_probe"
    ACTION = "action"
    INTEGRATION = "integration"


@dataclass(frozen=True)
class FlowStep:
    phase: FlowPhase
    title: str
    instruction_for_model: str


def session_flow_steps() -> List[FlowStep]:
    """セッション設計：各ターンでモデルが意識するフェーズの意図。"""
    return [
        FlowStep(
            FlowPhase.INTAKE,
            "受け取り",
            "ユーザーの言葉を鵜呑みにせず、事実と解釈を分けて聴く。",
        ),
        FlowStep(
            FlowPhase.MIRROR,
            "鏡",
            "状態を整理するが、一般論でまとめない。その人の語彙で最小限に反射する。",
        ),
        FlowStep(
            FlowPhase.YESNO_PROBE,
            "YES/NO",
            "軽さ・拡張・自然さ vs 重さ・義務・違和感。断定せず仮説として提示する。",
        ),
        FlowStep(
            FlowPhase.ACTION,
            "一致行動",
            "48時間以内・小さく具体的・実行可能な一歩のみ。正解を与えない。",
        ),
        FlowStep(
            FlowPhase.INTEGRATION,
            "統合",
            "次の自己観察のための問いかけで締める。無理にポジティブにしない。",
        ),
    ]


def next_phase(current: FlowPhase | None) -> FlowPhase:
    order = list(FlowPhase)
    if current is None:
        return FlowPhase.INTAKE
    try:
        i = order.index(current)
    except ValueError:
        return FlowPhase.INTAKE
    return order[min(i + 1, len(order) - 1)]
