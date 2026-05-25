from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lib.consciousness_mapper import ConsciousnessInsight, map_signals_to_consciousness
from nav_diagnosis_ai.theory_loader import load_theory_snippets, q2_theory_key


@dataclass(frozen=True)
class QuizResult:
    state_organization: str
    misalignment_tendency: str
    yesno_hypothesis: str
    one_liner: str
    cta_lead: str
    score_summary: Dict[str, int]
    verdict_key: str
    verdict_label: str
    verdict_caption: str
    theme: str
    current_state: str
    supplement: str
    theory_core: Tuple[str, ...]
    theory_verdict: Tuple[str, ...]
    theory_q2_note: str
    theory_practice_intro: str
    theory_practice_items: Tuple[str, ...]
    consciousness_level: int
    consciousness_label: str
    consciousness_emotion: str
    consciousness_position: str
    alignment_state: str
    misalignment_reason: str
    body_signal_summary: str
    future_if_aligned: str
    next_step: str
    energy_score: int


def _md_bold_to_html(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)


def _fmt_paragraphs(paragraphs: List[str]) -> Tuple[str, ...]:
    return tuple(_md_bold_to_html(p) for p in paragraphs)


def _signal_nuance(tally: Dict[str, int]) -> str:
    bits: List[str] = []
    if tally.get("body_heavy") or tally.get("body_tense"):
        bits.append("重さや緊張の感覚も選ばれています")
    if tally.get("body_yes"):
        bits.append("軽さ・広がりの感覚も選ばれています")
    if tally.get("yes_fear"):
        bits.append("「やりたさ」と「怖さ」が同時に出ています")
    if tally.get("obligation", 0) >= 2:
        bits.append("義務感・べき論のサインが強めに出ています")
    if not bits:
        return "選択と記述のバランスから、いまの状態を読み取りました。"
    return "／".join(bits) + "。"


_TEXT_NO_PATTERNS = [
    (r"やるべき", "obligation_text"),
    (r"すべき", "obligation_text"),
    (r"やらなきゃ", "obligation_text"),
    (r"しなきゃ", "obligation_text"),
    (r"しないと", "obligation_text"),
    (r"義務", "obligation_text"),
]

_TEXT_YES_PATTERNS = [
    (r"やりたい(けど|が|のに)", "want_fear_text"),
    (r"怖い", "fear_text"),
    (r"不安", "anxiety_text"),
]

_TEXT_MISALIGN_PATTERNS = [
    (r"重い", "heavy_text"),
    (r"しんどい", "heavy_text"),
    (r"緊張", "tense_text"),
    (r"縮まる", "tense_text"),
]

_TEXT_YES_BODY = [
    (r"軽い", "light_text"),
    (r"広が", "expand_text"),
    (r"ホッと", "light_text"),
]


def _scan_text(text: str) -> Dict[str, int]:
    t = text or ""
    scores: Dict[str, int] = {}

    def _bump_any(patterns: List[Tuple[str, str]], key: str) -> None:
        for pat, _ in patterns:
            if re.search(pat, t):
                scores[key] = scores.get(key, 0) + 1
                return

    _bump_any(_TEXT_NO_PATTERNS, "no")
    for pat, _ in _TEXT_YES_PATTERNS:
        if re.search(pat, t):
            scores["yes"] = scores.get("yes", 0) + 1
            if "けど" in pat or "怖" in pat:
                scores["yes_fear"] = scores.get("yes_fear", 0) + 1
            break
    _bump_any(_TEXT_MISALIGN_PATTERNS, "misalignment")
    if any(re.search(pat, t) for pat, _ in _TEXT_YES_BODY):
        scores["yes"] = scores.get("yes", 0) + 1
        scores["body_yes"] = scores.get("body_yes", 0) + 1
    return scores


def _accumulate_signals(
    tally: Dict[str, int],
    signals: Dict[str, int],
) -> None:
    for k, v in signals.items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        tally[k] = tally.get(k, 0) + n


def _score_from_answers(
    answers: Dict[str, Any],
    questions: List[Dict[str, Any]],
) -> Dict[str, int]:
    tally: Dict[str, int] = {}

    q2 = next((q for q in questions if q.get("id") == "q2"), None)
    if q2 and answers.get("q2"):
        val = str(answers["q2"])
        for opt in q2.get("options") or []:
            if opt.get("value") == val:
                _accumulate_signals(tally, opt.get("signals") or {})
                break

    q3 = next((q for q in questions if q.get("id") == "q3"), None)
    if q3:
        selected = answers.get("q3")
        if isinstance(selected, str):
            selected = [selected] if selected else []
        if isinstance(selected, list):
            sel_set = set(selected)
            for opt in q3.get("options") or []:
                if opt.get("value") in sel_set:
                    _accumulate_signals(tally, opt.get("signals") or {})

    combined_text = " ".join(
        [
            str(answers.get("q1") or ""),
            str(answers.get("q4") or ""),
            str(answers.get("q5") or ""),
        ]
    )
    text_hits = _scan_text(combined_text)
    for k, v in text_hits.items():
        tally[k] = tally.get(k, 0) + v

    return tally


def _verdict(tally: Dict[str, int]) -> Tuple[str, str]:
    """内部ラベルと、表示用の短い根拠メモ。"""
    no = tally.get("no", 0) + tally.get("obligation", 0) * 2
    yes = tally.get("yes", 0) + tally.get("body_yes", 0) + tally.get("yes_fear", 0)
    mis = tally.get("misalignment", 0) + tally.get("body_heavy", 0) + tally.get("body_tense", 0)

    parts = []
    if no >= 3:
        parts.append("選択・記述にNO寄りの手がかり")
    if tally.get("yes_fear"):
        parts.append("やりたさと怖さの同居")
    if mis >= 2:
        parts.append("重さ・緊張の感覚")
    if tally.get("body_yes"):
        parts.append("軽さ・広がりの感覚")

    memo = "、".join(parts[:4]) if parts else "選択と記述のバランス"

    if tally.get("mixed", 0) >= 1 and no <= 2 and yes <= 2:
        return "mixed", memo

    if mis >= 3 and yes >= 3:
        return "mixed", memo

    if no > yes + 1:
        return "no_lean", memo

    if yes > no + 1:
        return "yes_lean", memo

    return "mixed", memo


def _verdict_display(verdict: str) -> Tuple[str, str]:
    if verdict == "yes_lean":
        return "YES寄り", "軽さや「向かいたさ」の手がかりが、いまはやや強めに見えます。"
    if verdict == "no_lean":
        return "NO寄り", "重さや「やらなきゃ」に近い手がかりが、いまはやや強めに見えます。"
    return "混在", "YES と NO が同居しやすい段階です。急いで決めなくて大丈夫です。"


def _energy_score_from_tally(tally: Dict[str, int]) -> int:
    yes = tally.get("yes", 0) * 12
    body_yes = tally.get("body_yes", 0) * 10
    noise = tally.get("no", 0) * 10
    obligation = tally.get("obligation", 0) * 12
    mis = tally.get("misalignment", 0) * 10
    body_no = (tally.get("body_heavy", 0) + tally.get("body_tense", 0)) * 12
    mixed = tally.get("mixed", 0) * 6
    fear = tally.get("yes_fear", 0) * 8
    raw = 52 + yes + body_yes - noise - obligation - mis - body_no - mixed - fear
    return max(0, min(100, raw))


def compute_result(answers: Dict[str, Any], questions: List[Dict[str, Any]]) -> QuizResult:
    theme = (answers.get("q1") or "").strip()
    current = (answers.get("q4") or "").strip()
    free = (answers.get("q5") or "").strip()

    tally = _score_from_answers(answers, questions)
    energy_score = _energy_score_from_tally(tally)
    verdict, _memo = _verdict(tally)
    consciousness: ConsciousnessInsight = map_signals_to_consciousness(
        energy_score=energy_score,
        yes_score=tally.get("yes", 0),
        noise_score=tally.get("no", 0),
        body_positive_score=tally.get("body_yes", 0),
        body_negative_score=tally.get("body_heavy", 0) + tally.get("body_tense", 0),
        mixed_score=tally.get("mixed", 0),
        obligation_score=tally.get("obligation", 0),
        yes_fear_score=tally.get("yes_fear", 0),
        theme=theme or "いまのテーマ",
    )
    th = load_theory_snippets()

    state_organization = (
        "いまのテーマと状態を、次のように受け取りました。"
        f"\n\n【テーマ】\n{theme or '（未記入）'}"
        f"\n\n【いまの状態】\n{current or '（未記入）'}"
    )
    if free and free != "なし":
        state_organization += f"\n\n【補足】\n{free}"

    v_label, v_caption = _verdict_display(verdict)
    supplement = "" if (not free or free == "なし") else free

    interp = (th.get("interpretation") or {}).get(verdict, "")
    nuance = _signal_nuance(tally)
    misalignment_tendency = _md_bold_to_html(
        f"{interp} {nuance} いまは『{consciousness.alignment_state}』として読むのが自然です。"
    )

    yc = (th.get("yesno_compact") or {}).get(verdict, "")
    yesno_hypothesis = _md_bold_to_html(yc) if yc else ""

    theory_core = _fmt_paragraphs(list(th.get("core") or []))
    v_layers = (th.get("verdict_layers") or {}).get(verdict) or []
    theory_verdict = _fmt_paragraphs(list(v_layers))

    q2k = q2_theory_key(str(answers.get("q2") or ""))
    q2_raw = (th.get("q2_bridge") or {}).get(q2k, "")
    theory_q2_note = _md_bold_to_html(q2_raw) if q2_raw else ""

    pr = th.get("practice") or {}
    theory_practice_intro = _md_bold_to_html(str(pr.get("intro") or ""))
    theory_practice_items = tuple(
        _md_bold_to_html(str(x)) for x in (pr.get("items") or []) if str(x).strip()
    )

    hook = str(th.get("cta_theory_hook") or "").strip()
    cta_lead = (
        f"{hook} "
        "有料の深掘り版では、あなたの記述を土台に個別の言葉へ落とし、"
        "次の一歩まで伴走形式で扱います（一般論だけのまとめにはしません）。"
    ).strip()

    if verdict == "no_lean":
        one_liner = "いまは「正しいかどうか」より先に、**体に力が入っていないか・息が通るか**を先に確かめていい。"
    elif verdict == "yes_lean":
        one_liner = "小さな一致から試せます。**一晩置いても静かに残るか**、それだけ体に聞いてみてください。"
    else:
        one_liner = "急がなくていい。**数日単位で軽さと重さのどちらが続くか**だけ観察するのが、いまの一歩です。"

    one_liner = _md_bold_to_html(one_liner)

    return QuizResult(
        state_organization=state_organization.strip(),
        misalignment_tendency=misalignment_tendency.strip(),
        yesno_hypothesis=yesno_hypothesis.strip(),
        one_liner=one_liner.strip(),
        cta_lead=cta_lead.strip(),
        score_summary=dict(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))),
        verdict_key=verdict,
        verdict_label=v_label,
        verdict_caption=v_caption,
        theme=theme or "（未記入）",
        current_state=current or "（未記入）",
        supplement=supplement,
        theory_core=theory_core,
        theory_verdict=theory_verdict,
        theory_q2_note=theory_q2_note,
        theory_practice_intro=theory_practice_intro,
        theory_practice_items=theory_practice_items,
        consciousness_level=consciousness.consciousness_level,
        consciousness_label=consciousness.consciousness_label,
        consciousness_emotion=consciousness.consciousness_emotion,
        consciousness_position=consciousness.level_position_text,
        alignment_state=consciousness.alignment_state,
        misalignment_reason=consciousness.misalignment_reason,
        body_signal_summary=consciousness.body_signal_summary,
        future_if_aligned=consciousness.future_if_aligned,
        next_step=consciousness.next_action,
        energy_score=consciousness.energy_score,
    )
