from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from soul_nav_ai.actions import ACTION_RULES_TEXT
from soul_nav_ai.diagnosis import DiagnosisResult, analyze_text
from soul_nav_ai.flow import FlowPhase, session_flow_steps
from soul_nav_ai.yesno import YesNoLean, lean_from_diagnosis, lean_label_ja


@dataclass(frozen=True)
class TurnOutput:
    state_organization: str
    discrepancy: str
    yesno_hypothesis: str
    aligned_action: str
    followup_question: str
    phase: str
    preliminary_lean: str

    def sections_for_display(self) -> List[tuple[str, str]]:
        return [
            ("状態の整理", self.state_organization),
            ("ズレの指摘", self.discrepancy),
            ("YES/NOの仮説", self.yesno_hypothesis),
            ("一致行動", self.aligned_action),
            ("問いかけ", self.followup_question),
        ]


_JSON_KEYS = (
    "state_organization",
    "discrepancy",
    "yesno_hypothesis",
    "aligned_action",
    "followup_question",
)


def _turn_output_total_chars(out: TurnOutput) -> int:
    return sum(len(getattr(out, k)) for k in _JSON_KEYS)


def _parse_turn_output(
    data: Optional[Dict[str, Any]], phase: FlowPhase, lean: YesNoLean
) -> Optional[TurnOutput]:
    if not data:
        return None
    if not all(isinstance(data.get(k), str) and data.get(k, "").strip() for k in _JSON_KEYS):
        return None
    return TurnOutput(
        state_organization=str(data["state_organization"]).strip(),
        discrepancy=str(data["discrepancy"]).strip(),
        yesno_hypothesis=str(data["yesno_hypothesis"]).strip(),
        aligned_action=str(data["aligned_action"]).strip(),
        followup_question=str(data["followup_question"]).strip(),
        phase=phase.value,
        preliminary_lean=lean.value,
    )


def _soul_nav_min_output_chars() -> int:
    """推奨の合計文字数（下回ったら signals に記録する。API は再呼び出ししない）。"""
    raw = os.environ.get("SOUL_NAV_MIN_OUTPUT_CHARS", "1100").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 1100


def _output_length_signals(out: TurnOutput) -> Dict[str, Any]:
    total = _turn_output_total_chars(out)
    min_total = _soul_nav_min_output_chars()
    by_field = {k: len(getattr(out, k)) for k in _JSON_KEYS}
    return {
        "output_total_chars": total,
        "output_min_chars_recommended": min_total,
        "output_below_recommended": bool(min_total > 0 and total < min_total),
        "output_chars_by_field": by_field,
    }


def _safe_int_env(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(min_value, min(max_value, value))


def _soul_type_context_block(ctx: Dict[str, Any]) -> str:
    name = str(ctx.get("type_name") or "").strip() or "（不明）"
    summary = str(ctx.get("summary") or "").strip()
    scores = ctx.get("scores_by_name")
    scores_txt = ""
    if isinstance(scores, dict) and scores:
        parts = [f"{k}: {v}" for k, v in scores.items()]
        scores_txt = " / ".join(parts)
    strengths = ctx.get("strengths")
    pitfalls = ctx.get("pitfalls")
    st_txt = ""
    if isinstance(strengths, list) and strengths:
        st_txt = "；".join(str(x) for x in strengths[:4])
    pit_txt = ""
    if isinstance(pitfalls, list) and pitfalls:
        pit_txt = "；".join(str(x) for x in pitfalls[:4])
    lines = [
        "【魂タイプ診断結果（参考情報）】",
        f"- タイプ名: {name}",
    ]
    if summary:
        lines.append(f"- 要約: {summary}")
    if scores_txt:
        lines.append(f"- スコア内訳（表示名→値）: {scores_txt}")
    if st_txt:
        lines.append(f"- 強みの傾向: {st_txt}")
    if pit_txt:
        lines.append(f"- つまずきやすい傾向: {pit_txt}")
    lines.append(
        "※ラベルに乗せない。身体感覚・いまのズレと矛盾したらこの参照は捨ててよい。"
    )
    snap = ctx.get("ten_quiz_snapshot")
    if isinstance(snap, str) and snap.strip():
        lines.append("")
        lines.append("【10問リッカートの回答（一次データ・診断時点）】")
        lines.append(snap.strip())
        lines.append(
            "※タイプ名・スコアより、こちらの回答パターンを優先して読んでもよい。"
            "いまの発話・身体感覚と矛盾するなら対話と体感を優先。"
        )
    brief = ctx.get("premium_coaching_brief")
    if isinstance(brief, str) and brief.strip():
        lines.append("")
        lines.append("【本格レポート要約（モデル内参照用。ユーザーに読み上げ直したり繰り返さない）】")
        lines.append(brief.strip())
    return "\n".join(lines)


def _flow_prompt_block(phase: FlowPhase) -> str:
    steps = session_flow_steps()
    lines = ["【いまのセッション・フェーズ】", f"- 主フェーズ: {phase.value}"]
    for s in steps:
        mark = "→" if s.phase == phase else "-"
        lines.append(f"{mark} {s.phase.value}: {s.instruction_for_model}")
    return "\n".join(lines)


def build_system_prompt(phase: FlowPhase, soul_type_context: Optional[Dict[str, Any]] = None) -> str:
    flow = _flow_prompt_block(phase)
    soul_block = ""
    if soul_type_context:
        soul_block = "\n" + _soul_type_context_block(soul_type_context) + "\n"
    premium_mode = ""
    if soul_type_context and soul_type_context.get("premium_linked"):
        premium_mode = """
【本格レポート連携モード（品質要件）】
- ユーザーは直前に、10問診断と講座理論に基づく本格レポートを読んだ直後です。
- 「10問リッカートの回答」はレポートより生の一次データ。レポートの解釈とズレる場合は、リッカートのパターンと身体感覚を手がかりにする。
- 身体感覚・いまの違和感とレポートの見立てが矛盾する場合は、身体・体験を優先する（レポートは捨ててよい）。
- 抽象論や一般論・テンプレでまとめない。上記「本格レポート要約」に触れたテーマ線に沿って、ズレの仮説と一致行動を一段具体化する。
- レポート本文の言い換え・要約でターンを終わらせない。対話として「次の自己観察」と「48時間以内の一歩」に進める。
"""
    return f"""あなたは「魂のナビAI」です。
{soul_block}{premium_mode}
目的:
- ユーザーの迷いを「解決」して正解を出すことではない
- 身体感覚ベースのYES/NOを仮説として明確にし、その仮説に揃う小さな行動を一つだけ提案する
- この対話は「魂のナビの受信状態」を整えるためのもの。意識レベルそのものを説教調に説明するのではなく、**ノイズ / 受信中だが迷い / 一致** の翻訳で扱う

診断の原則:
- 表面的な悩みと本音のズレを疑う（言語をそのまま信じない）
- 「やるべき」「〜しなきゃ」などのべき論はNO寄りの手がかりとして扱う（断定はしない）
- 「やりたいけど怖い」などはYES寄りの手がかりとして扱う（断定はしない）
- 重要なのは「高い状態か」より、**その状態と行動が一致しているか**。頭で理解していても身体が縮むならズレとして扱う
- エネルギーが高くても方向がズレている場合がある。勢いを賞賛する前に、身体の軽さ・広がり・違和感を確認する

YESの手がかり（仮説用）:
- 軽さ、拡張感、自然さ

NOの手がかり（仮説用）:
- 重さ、義務感、違和感

禁止事項:
- 正解・最善・これだけやればOK、などの断定や指示の押し付けをしない
- 一般論やテンプレでまとめない（その人の語彙・状況に接続する）
- 無理にポジティブにしない（重さや怖さを消さない）

{ACTION_RULES_TEXT}

{flow}

【分量・対話型コーチングとしての密度】
- 本格レポートは「長文の地図」、ここは「対話型コーチングの厚み」。**短文のチャット返信のように済ませない。**
- **5項目の合計**で、日本語 **おおよそ 1200〜2600 文字**を目安にする（JSONのエスケープは除き、各値の本文の長さで考える）。
- 各長文キーは**2段落以上**に分けてよい（改行で区切る）。「起きていること」→「そこから読み取れるズレ／身体」→「だから次の一歩は…」のように**展開のレイヤーを複数**入れる。
- 各キーに、**ユーザー固有の語句を1か所以上引用**し、**身体感覚・場面・感情**を具体的に置く（抽象語だけの段落にしない）。
- 「ズレの指摘」「YES/NOの仮説」は、**なぜそう読み取ったか**の根拠を**複数文**で示す。
- 必要に応じて、受信状態を「ノイズ状態」「受信しているが迷っている状態」「一致し始めている状態」などの自然な日本語で言い換える。
- 「一致行動」は**いつ・どこで・どれくらい**が分かるようにし、**この一歩が魂のナビ講座で深められるテーマ**にそっと触れてよい（売り込み口調・断定は禁止のまま）。
- ※極端に短いユーザー入力はアプリ側で弾かれることがあるため、届いた入力はある程度の文脈がある前提でよい。

出力は次のJSONオブジェクトのみ（前後に説明文を付けない）。日本語で。
キーは必ず次の通り。**各値は次の日本語文字数目安の下限を意識し、それ以上を目指す**（短くまとめない）:
{{
  "state_organization": "状態の整理（1）。ユーザーの言葉を鏡のように言い換え、いま立っている場所を立体的に。**220文字以上**を目安に。",
  "discrepancy": "ズレの指摘（2）。言葉と身体・本音と義務の二層に触れ、根拠を**複数文**で。**220文字以上**を目安に。",
  "yesno_hypothesis": "YES/NOの仮説（3）。断定せず、仮説の根拠・揺れ・身体の観察を厚く。**160文字以上**を目安に。",
  "aligned_action": "一致行動（4）。48時間以内・実行可能な1つ。**120文字以上**。いつ・どこ・所要時間の目安を必ず含める。",
  "followup_question": "問いかけ（5）。**2文以上**。次の自己観察を促す。**110文字以上**を目安に。誘導尋問にしない。"
}}
"""


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    candidate = text.strip()
    if not candidate.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", candidate)
        if m:
            candidate = m.group(0).strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _fallback_output(
    user_text: str,
    diagnosis: DiagnosisResult,
    lean: YesNoLean,
    phase: FlowPhase,
    soul_type_context: Optional[Dict[str, Any]] = None,
) -> TurnOutput:
    lean_txt = lean_label_ja(lean)
    type_hint = ""
    if soul_type_context and str(soul_type_context.get("type_name") or "").strip():
        type_hint = f"（参考：魂タイプ診断では「{soul_type_context.get('type_name')}」傾向。身体感覚と違えば無視してよい）"
    ut = user_text.strip()
    preview = ut[:320] + ("…" if len(ut) > 320 else "")
    return TurnOutput(
        state_organization=(
            f"{type_hint}（オフライン・たたき台）いま語られていることの要約に留まらず、次の発話から読み取れるレイヤーを置きます。"
            f"手がかりの抜粋：{preview}"
        ).strip(),
        discrepancy="（API未設定または生成失敗のため簡易表示）言葉の奥にある『べき』と『本当は』の二重性を、身体感覚で確認する必要があります。"
        " 本番では、ここを根拠つきで数段落に展開します。",
        yesno_hypothesis=f"ルールベースのたたき台：{lean_txt}。仮説であり、身体の感覚で再チェックしてください。"
        " 本番のプレミアム応答では、YES/NOの揺れと観察の言葉をもっと厚く書きます。",
        aligned_action="48時間以内の一致行動の例：このテーマについて紙に3行だけ書く（事実1行／感情1行／身体の感覚1行）。"
        " 本番では手順・時間の目安まで含めた長めの一文になります。",
        followup_question="いまの一文を話しているとき、胸・お腹・肩のどこが一番反応しましたか？ その感覚を一言足りないところまで言語化すると、次の一歩が見えやすくなります。",
        phase=phase.value,
        preliminary_lean=lean.value,
    )


def process_turn(
    *,
    user_text: str,
    phase: FlowPhase,
    openai_client: Any | None,
    model: str,
    soul_type_context: Optional[Dict[str, Any]] = None,
) -> tuple[TurnOutput, DiagnosisResult, Dict[str, Any]]:
    """診断シグナル算出 →（可能なら）モデル生成。戻り値: 出力, 診断, シグナル辞書（保存用）。"""
    diagnosis = analyze_text(user_text)
    lean = lean_from_diagnosis(diagnosis)
    signals: Dict[str, Any] = {
        "preliminary_lean": lean.value,
        "diagnosis": {
            "obligation_hits": list(diagnosis.obligation_hits),
            "desire_fear_hits": list(diagnosis.desire_fear_hits),
            "surface_phrases": list(diagnosis.surface_phrases),
            "contradiction_markers": list(diagnosis.contradiction_markers),
            "notes_for_model": diagnosis.notes_for_model,
        },
    }

    if openai_client is None:
        out = _fallback_output(user_text, diagnosis, lean, phase, soul_type_context)
        return out, diagnosis, signals

    user_lines = [
        diagnosis.to_prompt_block(),
        "",
        f"[ルールベース仮説] {lean_label_ja(lean)}",
        "",
    ]
    if soul_type_context:
        user_lines.extend([_soul_type_context_block(soul_type_context), ""])
    user_lines.extend(
        [
            "[ユーザーの入力]",
            user_text.strip(),
        ]
    )
    user_payload = "\n".join(user_lines)

    temp = 0.42 if (soul_type_context or {}).get("premium_linked") else 0.55
    # 環境変数が壊れていても 500 を出さず、既定値で継続する。
    max_tok = _safe_int_env("SOUL_NAV_MAX_TOKENS", 4096, min_value=256, max_value=4500)
    try:
        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": build_system_prompt(phase, soul_type_context)},
                {"role": "user", "content": user_payload},
            ],
            temperature=temp,
            max_tokens=max_tok,
        )
        text = (resp.choices[0].message.content or "").strip()
        data = _parse_json_object(text)
        out = _parse_turn_output(data, phase, lean)
        if not out:
            out = _fallback_output(user_text, diagnosis, lean, phase, soul_type_context)
            return out, diagnosis, {**signals, "model_error": "invalid_json_or_empty_fields"}

        signals = {**signals, **_output_length_signals(out)}
        return out, diagnosis, signals
    except Exception as e:
        out = _fallback_output(user_text, diagnosis, lean, phase, soul_type_context)
        return out, diagnosis, {**signals, "model_error": f"{type(e).__name__}: {e}"}


def openai_client_or_none() -> Any | None:
    try:
        from openai import OpenAI
    except Exception:  # pragma: no cover
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return OpenAI(api_key=api_key)
