"""有料向け：10問回答＋講座理論を踏まえた OpenAI レポート生成。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


class PremiumReportGenerationError(Exception):
    """OpenAI 呼び出し失敗など。メッセージをそのまま画面に出してよい想定。"""


def _theory_snippets_path() -> Path:
    return Path(__file__).resolve().parent / "nav_diagnosis_ai" / "theory_snippets.json"


def load_theory_compact(max_chars: int = 8000) -> str:
    """講座要約（theory_snippets.json）をプロンプト用に連結する。"""
    p = _theory_snippets_path()
    if not p.is_file():
        return ""
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return ""
    parts: List[str] = []
    if isinstance(raw.get("core"), list):
        for x in raw["core"]:
            if isinstance(x, str):
                parts.append(x)
    vl = raw.get("verdict_layers")
    if isinstance(vl, dict):
        for _k, arr in vl.items():
            if isinstance(arr, list):
                for x in arr:
                    if isinstance(x, str):
                        parts.append(x)
    if isinstance(raw.get("practice"), dict):
        pr = raw["practice"]
        intro = pr.get("intro")
        if isinstance(intro, str):
            parts.append(intro)
        items = pr.get("items")
        if isinstance(items, list):
            for x in items:
                if isinstance(x, str):
                    parts.append(x)
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n（以下略）"
    return text


def _likert_label(val: int, likert_choices: List[Tuple[int, str]]) -> str:
    for v, lab in likert_choices:
        if v == val:
            return lab
    return str(val)


def generate_premium_ai_report(
    *,
    soul_type_name: str,
    soul_type_key: str,
    soul_summary: str,
    soul_strengths: List[str],
    soul_pitfalls: List[str],
    scores_by_name: Dict[str, int],
    qa_lines: List[str],
    likert_choices: List[Tuple[int, str]],
    focus: str = "",
    free_text: str = "",
) -> Optional[Dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        if not api_key:
            print("[premium_report] skipped: OPENAI_API_KEY is not set")
        if OpenAI is None:
            print("[premium_report] skipped: OpenAI SDK is not available")
        return None

    theory = load_theory_compact()
    scores_line = ", ".join(f"{k}: {v}" for k, v in sorted(scores_by_name.items(), key=lambda x: -x[1]))
    qa_block = "\n".join(qa_lines)

    system = """あなたは「魂のナビ講座」の認定コーチとして、30問診断の結果に基づき個人向けレポートを書きます。
講座では「心のナビ」と「魂のナビ」の二層、迷いの意味、体感でのYES/NOの読み方などが核です。
ユーザーの回答パターンと魂タイプを統合し、一般論や言い換えだけで終わらせないこと。
出力は指定のJSONのみ（前後に説明文を付けない）。日本語。"""

    user = f"""▼講座理論（要約・参照用。これをそのまま転記せず、その人に届く言葉に再構成すること）
{theory if theory else "（理論ファイルが読み取れませんでした。魂タイプと回答から講座らしい視点で書いてください。）"}

▼診断メタ
- 魂タイプキー: {soul_type_key}
- 魂タイプ名: {soul_type_name}
- タイプの短い説明: {soul_summary}
- タイプの典型的な強み（参考）: {soul_strengths}
- タイプの典型的な落とし穴（参考）: {soul_pitfalls}
- スコア（タイプ名→点数）: {scores_line}

▼30問の回答（質問文と選択）
{qa_block}

▼ユーザーが追加で伝えたいこと（任意）
- いま深めたいテーマ: {focus or "（未記入）"}
- 自由記述: {free_text or "（なし）"}

▼執筆ルール
1. 30問の傾向（どの軸が強いか・中立が多いか等）に触れ、タイプ名のラベル貼りで終わらない。
2. 講座の「2つのナビ」「体感照合」「揺れ期」などの概念を、**この人の回答から読み取れる文脈**に接続する。
3. ユーザーの自由記述やテーマに具体的に応答する。問いがあれば答える。
4. 暖かく寄り添いつつ、実行可能な一歩まで落とす。next_actions は「何を・いつ・どのくらい」まで。
5. 説教調・「〜となります」の連発を避ける。

▼出力JSONスキーマ（キーは必ずすべて含める）
{{
  "opening": "2〜4段落。共感から入り、この人の30問パターンとタイプを統合した全体像。",
  "type_in_depth": "タイプの強み・癖を、この人の回答に即して深掘りした本文（2〜3段落）。",
  "navigation_map": "心のナビ／魂のナビの観点で、いまのフェーズを講座の地図に載せた説明（2段落程度）。",
  "empathy": "共感の一文",
  "problem": "いま起きていそうなこと（その人専用）",
  "cause": "背景の読み（講座概念と接続）",
  "if_unchanged": "このまま進んだときに起こりうること",
  "with_course": "魂のナビで進んだときに見えてくる未来",
  "this_week_action": "今週できる具体的一歩（1〜2文）",
  "strengths": ["3〜5個、具体的に"],
  "pitfalls": ["3〜5個、責めずに"],
  "next_actions": ["今日〜今週の具体行動1", "具体行動2", "具体行動3"],
  "closing": "短い締めの一文"
}}

likertの意味: {_likert_label(1, likert_choices)} … {_likert_label(5, likert_choices)}
"""

    client = OpenAI(api_key=api_key)
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system.strip()},
                {"role": "user", "content": user.strip()},
            ],
            temperature=0.65,
        )
        if not resp.choices:
            return None
        text = (resp.choices[0].message.content or "").strip()
        if not text:
            return None
        candidate = text
        if not (candidate.startswith("{") and candidate.endswith("}")):
            m = re.search(r"\{[\s\S]*\}", candidate)
            if m:
                candidate = m.group(0).strip()
        data = json.loads(candidate)
        if not isinstance(data, dict):
            return None
        required_str = (
            "opening",
            "type_in_depth",
            "navigation_map",
            "empathy",
            "problem",
            "cause",
            "if_unchanged",
            "with_course",
            "this_week_action",
            "closing",
        )
        for k in required_str:
            if not isinstance(data.get(k), str):
                return None
        for k in ("strengths", "pitfalls", "next_actions"):
            v = data.get(k)
            if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                return None
        return data
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        print(f"[premium_report] generation failed: {detail}")
        raise PremiumReportGenerationError(
            "OpenAI へのリクエストに失敗しました。"
            " .env の OPENAI_MODEL（推奨 gpt-4o-mini）と API キー、VPS から api.openai.com への通信を確認してください。"
            " Gunicorn の worker タイムアウトが 30 秒のままだと、生成が間に合わず切断されることがあります（--timeout 120 以上を推奨）。"
            f" 参考: {detail[:400]}"
        ) from e
