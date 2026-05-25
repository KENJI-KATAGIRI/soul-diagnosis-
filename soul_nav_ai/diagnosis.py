from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class DiagnosisResult:
    """テキストから抽出した診断シグナル（言語をそのまま信じないための材料）。"""

    obligation_hits: Tuple[str, ...] = ()
    desire_fear_hits: Tuple[str, ...] = ()
    surface_phrases: Tuple[str, ...] = ()
    contradiction_markers: Tuple[str, ...] = ()
    notes_for_model: str = ""

    def to_prompt_block(self) -> str:
        lines = [
            "[診断シグナル（ルールベース。ユーザーの言葉を鵜呑みにしないこと）]",
            f"- NO寄り語彙の検出: {list(self.obligation_hits) or '（該当なし）'}",
            f"- YES寄り語彙の検出: {list(self.desire_fear_hits) or '（該当なし）'}",
            f"- 表面ストーリーっぽい語彙: {list(self.surface_phrases) or '（該当なし）'}",
            f"- 矛盾・割り切りの痕跡: {list(self.contradiction_markers) or '（該当なし）'}",
        ]
        if self.notes_for_model:
            lines.append(f"- 補足: {self.notes_for_model}")
        return "\n".join(lines)


_OBLIGATION_PATTERNS = [
    (r"やるべき", "やるべき"),
    (r"すべき", "すべき"),
    (r"しなきゃ", "しなきゃ"),
    (r"しなくちゃ", "しなくちゃ"),
    (r"しないと", "しないと"),
    (r"義務", "義務"),
    (r"正しい(こと|選択)?", "正しい"),
    (r"当然", "当然"),
    (r"〜ないわけには", "〜ないわけには"),
    (r"いかねば", "いかねば"),
    (r"せざるを得ない", "せざるを得ない"),
    (r"背負わなければ", "背負わなければ"),
    (r"期待に応え", "期待に応え"),
    (r"迷惑をかけ", "迷惑をかけ"),
]

_DESIRE_FEAR_PATTERNS = [
    (r"やりたい(けど|が|のに)", "やりたいけど/が/のに"),
    (r"本当は", "本当は"),
    (r"怖い", "怖い"),
    (r"恐れ", "恐れ"),
    (r"不安", "不安"),
    (r"惹か", "惹かれる系"),
    (r"ワクワク", "ワクワク"),
    (r"軽い", "軽い"),
    (r"自然", "自然"),
    (r"身体が", "身体が"),
    (r"胸が", "胸が"),
    (r"お腹が", "お腹が"),
]

_SURFACE_PATTERNS = [
    (r"みんなが", "みんなが"),
    (r"一般的に", "一般的に"),
    (r"常識的に", "常識的に"),
    (r"正解", "正解"),
    (r"ベスト", "ベスト"),
    (r"〜と言われ", "〜と言われ"),
    (r"〜というべき", "〜というべき"),
]

_CONTRADICTION_PATTERNS = [
    (r"でも", "でも"),
    (r"けど", "けど"),
    (r"一方で", "一方で"),
    (r"本音", "本音"),
    (r"建前", "建前"),
    (r"表向き", "表向き"),
    (r"ずれ", "ずれ"),
]


def _find_hits(text: str, patterns: List[Tuple[str, str]]) -> Tuple[str, ...]:
    t = text
    seen: List[str] = []
    for pat, label in patterns:
        if re.search(pat, t):
            if label not in seen:
                seen.append(label)
    return tuple(seen)


def analyze_text(text: str) -> DiagnosisResult:
    """表面的な悩みと本音のズレの手がかりを、語彙と構造から抽出する。"""
    raw = (text or "").strip()
    if not raw:
        return DiagnosisResult(notes_for_model="入力が空です。")

    obligation = _find_hits(raw, _OBLIGATION_PATTERNS)
    desire_fear = _find_hits(raw, _DESIRE_FEAR_PATTERNS)
    surface = _find_hits(raw, _SURFACE_PATTERNS)
    contra = _find_hits(raw, _CONTRADICTION_PATTERNS)

    notes: List[str] = []
    if obligation and desire_fear:
        notes.append("義務・べき論と欲求・怖れが同居している可能性が高い（ズレの候補）。")
    elif obligation and not desire_fear:
        notes.append("べき論が強い。言葉の奥に『本当は』が隠れていないか疑う。")
    elif desire_fear and not obligation:
        notes.append("欲求と身体反応の手がかりが見える。言葉より感覚側を優先してよい。")

    return DiagnosisResult(
        obligation_hits=obligation,
        desire_fear_hits=desire_fear,
        surface_phrases=surface,
        contradiction_markers=contra,
        notes_for_model=" ".join(notes),
    )
