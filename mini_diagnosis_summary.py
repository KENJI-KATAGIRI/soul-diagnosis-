"""無料診断向け：OpenAI で短い要約テキストのみ生成（JSONレポートより軽量）。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


class MiniSummaryError(Exception):
    """API 失敗・空応答など。"""


def _likert_label(val: int, choices: List[Tuple[int, str]]) -> str:
    for v, lab in choices:
        if v == val:
            return lab
    return str(val)


def build_strings_for_mini_summary(
    *,
    answers: Dict[str, int],
    questions: List[Any],
    likert_choices: List[Tuple[int, str]],
    best_key: str,
    soul_types: Mapping[str, Any],
    soul_type_priority: List[str],
    position_profile: Mapping[str, Any],
    manuscript_insight: Mapping[str, Any],
    soul_scores: Mapping[str, int],
    challenge_note: str = "",
) -> Dict[str, str]:
    """generate_mini_diagnosis_summary に渡す文字列ブロックを組み立てる。"""
    st = soul_types[best_key]
    name = getattr(st, "name", str(best_key))
    scores_summary = ", ".join(
        f"{getattr(soul_types[k], 'name', k)}:{int(soul_scores.get(k, 0))}" for k in soul_type_priority
    )
    position_summary = (
        f"フェーズ: {position_profile.get('phase_title', '')} — {position_profile.get('phase_body', '')}\n"
        f"ナビ: {position_profile.get('navi_title', '')} — {position_profile.get('navi_body', '')}"
    )
    if position_profile.get("sub_type_name"):
        position_summary += f"\n副次に近いタイプ: {position_profile['sub_type_name']}"

    theme_items = manuscript_insight.get("theme_items")
    if theme_items:
        theme_summary = "\n".join(f"- {t}: {b}" for _k, t, b in theme_items)
    else:
        theme_summary = str(manuscript_insight.get("theme_neutral_message") or "（突出テーマなし）")

    lines: List[str] = []
    for q in questions:
        v = answers.get(q.key)
        if v is None:
            continue
        lab = _likert_label(int(v), likert_choices)
        lines.append(f"- {q.key} [{lab}] {getattr(q, 'text', '')}")
    qa_compact = "\n".join(lines)

    return {
        "soul_type_name": name,
        "soul_type_key": best_key,
        "scores_summary": scores_summary,
        "position_summary": position_summary,
        "theme_summary": theme_summary,
        "qa_compact": qa_compact,
        "challenge_note": challenge_note.strip(),
    }


def generate_mini_diagnosis_summary(
    *,
    soul_type_name: str,
    soul_type_key: str,
    scores_summary: str,
    position_summary: str,
    theme_summary: str,
    qa_compact: str,
    challenge_note: str = "",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 200,
) -> str:
    """
    診断の集計テキストから、日本語のミニ要約（プレーンテキスト）を1回生成する。
    """
    key = (api_key or os.environ.get("OPENAI_API_KEY", "") or "").strip()
    if not key or OpenAI is None:
        raise MiniSummaryError("OPENAI_API_KEY が無いか、openai パッケージが利用できません。")

    m = (model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()

    system = """あなたは診断ツールの要約文ライターです。
与えられた診断データだけをもとに、読者一人向けの短い要約を書いてください。

ルール（厳守）:
- プレーンテキストのみ（見出し・記号・JSONは使わない）。
- 全体で 100〜150 日本語文字。1段落のみ。
- 講座・セッション・サービス・LINE・イベント名など固有のサービス名は絶対に書かない。
- タイプ名のラベル貼りだけで終わらず、フェーズかテーマを一言織り込む。
- ユーザーが「いまの課題」を書いている場合は、一言だけ触れる（否定・説教しない）。
- 医療・診断の断定はしない。「目安」「傾向」として書く。
- 最後の一文は必ず「なぜそうなりやすいのか、そのメカニズムは動画を見るとすっきり理解できます。」で締める。"""

    user = f"""▼魂タイプ
- キー: {soul_type_key}
- 表示名: {soul_type_name}

▼タイプスコア（参考）
{scores_summary}

▼いまの位置（フェーズ・ナビ）
{position_summary}

▼テーマ傾向
{theme_summary}

▼いまの課題・気になっていること（ユーザー記入・任意）
{challenge_note.strip() if challenge_note.strip() else "（未記入）"}

▼設問と回答（コンパクト）
{qa_compact}
"""

    client = OpenAI(api_key=key)
    try:
        resp = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": system.strip()},
                {"role": "user", "content": user.strip()},
            ],
            temperature=0.55,
            max_tokens=max(100, min(max_tokens, 300)),
        )
    except Exception as e:
        raise MiniSummaryError(f"OpenAI リクエスト失敗: {type(e).__name__}: {e}") from e

    if not resp.choices:
        raise MiniSummaryError("応答が空です（choices なし）。")
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise MiniSummaryError("応答テキストが空です。")
    return _sanitize_summary(text)


_BANNED_WORDS = ["魂のナビ", "講座", "セッション", "ご案内", "ご参加", "お申し込み", "LINE登録", "無料登録"]
_CLOSING = "なぜそうなりやすいのか、そのメカニズムは動画を見るとすっきり理解できます。"


def _sanitize_summary(text: str) -> str:
    """禁止ワードを含む文を除去し、締めの一文を確実に付ける。"""
    import re
    sentences = re.split(r'(?<=[。！？])', text)
    clean = [s for s in sentences if s.strip() and not any(w in s for w in _BANNED_WORDS)]
    body = "".join(clean).strip()
    if not body.endswith(_CLOSING):
        if body and not body.endswith("。"):
            body += "。"
        body += _CLOSING
    return body
