from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


STANDARD_CONSCIOUSNESS_LEVELS: Tuple[Tuple[int, str, str], ...] = (
    (20, "恥", "屈辱"),
    (30, "罪悪感", "非難"),
    (50, "無感動", "絶望感"),
    (75, "深い悲しみ", "後悔"),
    (100, "恐怖", "心配"),
    (125, "欲望", "切望"),
    (150, "怒り", "憎しみ"),
    (175, "プライド", "嘲笑"),
    (200, "勇気", "肯定"),
    (250, "中立", "信頼"),
    (310, "意欲", "楽天的"),
    (350, "受容", "許し"),
    (400, "理性", "理解"),
    (500, "愛", "崇敬"),
    (540, "喜び", "静穏"),
    (600, "平和", "至福"),
    (700, "悟り", "表現不能"),
)


@dataclass(frozen=True)
class ConsciousnessInsight:
    consciousness_level: int
    consciousness_label: str
    consciousness_emotion: str
    alignment_state: str
    misalignment_reason: str
    body_signal_summary: str
    future_if_aligned: str
    next_action: str
    energy_score: int
    level_position_text: str


def _clamp(val: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(val)))


def _level_position_text(level: int) -> str:
    if level < 200:
        return f"{level}付近。まだノイズに引っ張られやすく、受信状態を整える段階です。"
    if level < 310:
        return f"{level}付近。ナビを受け取り始めているが、迷いも残りやすい位置です。"
    if level < 500:
        return f"{level}付近。ナビの受信が安定し、一致した判断に近づいている位置です。"
    return f"{level}付近。ナビと一致しやすく、自然に行動へつながりやすい位置です。"


def _closest_standard_level(target: int) -> Tuple[int, str, str]:
    level, label, emotion = min(STANDARD_CONSCIOUSNESS_LEVELS, key=lambda item: abs(item[0] - target))
    return level, label, emotion


def _body_summary_from_signals(signals: Dict[str, int]) -> str:
    if signals.get("body_heavy", 0) + signals.get("body_tense", 0) >= 2:
        return "体は少し縮み気味で、重さや呼吸の浅さが出やすい状態です。"
    if signals.get("body_yes", 0) >= 2:
        return "体は少し緩みやすく、広がりや呼吸の深さが戻りやすい状態です。"
    return "体感はまだ揺れやすく、軽さと違和感が混ざりやすい状態です。"


def map_signals_to_consciousness(
    *,
    energy_score: int,
    yes_score: int,
    noise_score: int,
    body_positive_score: int,
    body_negative_score: int,
    mixed_score: int,
    obligation_score: int,
    yes_fear_score: int,
    theme: str,
) -> ConsciousnessInsight:
    alignment_delta = (yes_score + body_positive_score) - (noise_score + body_negative_score + obligation_score)

    if energy_score <= 30 or alignment_delta <= -3:
        alignment_state = "ノイズ状態"
    elif energy_score >= 80 and alignment_delta >= 3 and yes_fear_score == 0:
        alignment_state = "一致状態"
    else:
        alignment_state = "受信しているが迷っている状態"

    if obligation_score >= 2 and yes_score >= 2:
        misalignment_reason = "頭では前に進んだほうがいいと理解している一方で、行動が『やるべき』寄りになっていて、自然な一致になっていません。"
    elif yes_fear_score >= 1 and yes_score >= 2:
        misalignment_reason = "気持ちは動いているのに、不安がブレーキになり、感情と行動がまだ一致しきっていません。"
    elif energy_score >= 70 and alignment_delta < 2:
        misalignment_reason = "エネルギーはあるのに、向かう方向がまだ定まり切っておらず、強さだけで進もうとしてズレやすい状態です。"
    elif alignment_state == "ノイズ状態":
        misalignment_reason = "不安・義務感・重さの信号が強く、ナビの受信より先にノイズが前に出ています。"
    else:
        misalignment_reason = "感覚は受信できているものの、まだ確信より迷いが残っていて、一歩をどこに置くかが定まり切っていません。"

    if alignment_state == "一致状態":
        target_level = 350 if energy_score < 90 else 400
        future_if_aligned = f"{theme}に対して、考え込みすぎずに『これで進める』という静かな確信が生まれ、行動が軽くなりやすい状態です。"
        next_action = "今日か明日のうちに、いちばん軽く感じる選択を15分だけ試してください。終えたあとに呼吸が深くなるかだけ観察します。"
    elif alignment_state == "受信しているが迷っている状態":
        target_level = 250 if mixed_score > 0 else 310
        future_if_aligned = f"{theme}について、迷いはゼロでなくても『この方向なら違和感が少ない』という感覚が残り、次の一歩を小さく切れる状態です。"
        next_action = "48時間以内に、候補を1つだけ選び『やる/やらない』ではなく『10分だけ触れる』行動に落としてみてください。"
    else:
        target_level = 100 if body_negative_score >= 2 else 175
        future_if_aligned = f"{theme}に対して、まずノイズが静まり、重さではなく落ち着きから判断できる状態に戻っていきます。"
        next_action = "今日は結論を出さず、紙に『事実』『感情』『体の反応』を1行ずつ書き分けてください。判断はそのあとで十分です。"

    level, label, emotion = _closest_standard_level(target_level)
    body_signal_summary = _body_summary_from_signals(
        {
            "body_heavy": body_negative_score,
            "body_tense": body_negative_score,
            "body_yes": body_positive_score,
        }
    )
    return ConsciousnessInsight(
        consciousness_level=level,
        consciousness_label=label,
        consciousness_emotion=emotion,
        alignment_state=alignment_state,
        misalignment_reason=misalignment_reason,
        body_signal_summary=body_signal_summary,
        future_if_aligned=future_if_aligned,
        next_action=next_action,
        energy_score=_clamp(energy_score),
        level_position_text=_level_position_text(level),
    )


def map_type_scores_to_consciousness(
    *,
    scores_by_key: Dict[str, int],
    top_type_name: str,
) -> ConsciousnessInsight:
    vals: List[int] = [int(v) for v in scores_by_key.values()] if scores_by_key else [0]
    top = max(vals) if vals else 0
    second = sorted(vals, reverse=True)[1] if len(vals) > 1 else 0
    total = sum(vals)
    max_total = max(1, len(vals) * max(1, top))
    energy_score = _clamp(round(100 * total / max_total))
    spread = top - second

    if energy_score <= 30:
        alignment_state = "ノイズ状態"
        level_target = 100
        body = "体が縮みやすく、重さや浅い呼吸として出やすい状態です。"
        misalignment_reason = "全体のエネルギーが低く、判断より先に停滞や不安が前に出やすい状態です。"
        future = "まずノイズが下がると、『何が嫌か』ではなく『どちらが自然か』で選べるようになります。"
        action = "今日は大きな決断をせず、気になっている選択肢を1つだけ紙に書き出してください。"
    elif spread <= 1 and energy_score >= 60:
        alignment_state = "受信しているが迷っている状態"
        level_target = 250
        body = "広がりと違和感が混ざりやすく、決め切る直前で揺れやすい状態です。"
        misalignment_reason = "エネルギーはあるのに、複数の方向へ引っ張られていて、まだ一致した意思決定になっていません。"
        future = f"{top_type_name}の方向へ少し寄せるだけで、『これで進める』という静かな確信が戻りやすくなります。"
        action = f"{top_type_name}らしさが最も出る行動を1つだけ選び、15分で試してください。"
    elif energy_score >= 80 and spread >= 3:
        alignment_state = "一致状態"
        level_target = 350
        body = "体が少し緩みやすく、広がりや呼吸の深さとして現れやすい状態です。"
        misalignment_reason = "大きなズレは少なく、いまは迷いを減らすより『この一致を保つこと』が重要です。"
        future = f"{top_type_name}の強みを自然に使いながら、意思決定と行動がつながりやすい状態です。"
        action = f"{top_type_name}として最も軽い一歩を、今日のうちに1つ終わらせてください。"
    else:
        alignment_state = "受信しているが迷っている状態"
        level_target = 200
        body = "まだ揺れはあるものの、違和感の場所を見分けられれば受信は戻しやすい状態です。"
        misalignment_reason = "方向性のヒントはあるものの、頭と体が完全にはそろっておらず、決断の軸が安定していません。"
        future = f"{top_type_name}の軸に寄せていくと、迷いの量より『納得感』が先に整っていきます。"
        action = "次に進めたいテーマについて、『軽い / 重い』だけを基準に候補を並べ替えてみてください。"

    level, label, emotion = _closest_standard_level(level_target)
    return ConsciousnessInsight(
        consciousness_level=level,
        consciousness_label=label,
        consciousness_emotion=emotion,
        alignment_state=alignment_state,
        misalignment_reason=misalignment_reason,
        body_signal_summary=body,
        future_if_aligned=future,
        next_action=action,
        energy_score=energy_score,
        level_position_text=_level_position_text(level),
    )
