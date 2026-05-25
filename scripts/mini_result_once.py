#!/usr/bin/env python3
"""
ローカルで「無料診断のミニ要約」を1回だけ OpenAI に生成させるCLI。

使い方:
  cd プロジェクトルート
  ./.venv/bin/python scripts/mini_result_once.py --answers-json path/to/answers.json
  ./.venv/bin/python scripts/mini_result_once.py --demo

answers.json の例（q1〜q30 すべて 1〜5 の整数）:
  {"q1":4,"q2":3,...,"q30":3}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = ROOT / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def main() -> int:
    _load_dotenv()

    parser = argparse.ArgumentParser(description="無料診断ミニ要約を1回生成")
    parser.add_argument("--answers-json", type=Path, help="q1..q30 の回答 JSON ファイル")
    parser.add_argument("--demo", action="store_true", help="全問3（中立）のデモデータで生成")
    parser.add_argument("--max-tokens", type=int, default=900, help="出力側 max_tokens（既定 900）")
    parser.add_argument(
        "--challenge",
        default="",
        help="いまの課題・自由記述（任意）。ミニ要約プロンプトに含めます。",
    )
    args = parser.parse_args()

    if not args.demo and not args.answers_json:
        print("--answers-json か --demo を指定してください。", file=sys.stderr)
        return 2

    from app import (  # noqa: WPS433
        LIKERT_CHOICES,
        QUESTIONS,
        SOUL_TYPES,
        SOUL_TYPE_PRIORITY,
        pick_type,
        score_answers,
    )
    from diagnosis_axes import build_position_profile, score_diagnosis
    from diagnosis_manuscript import build_manuscript_insight, score_themes
    from mini_diagnosis_summary import (
        MiniSummaryError,
        build_strings_for_mini_summary,
        generate_mini_diagnosis_summary,
    )

    if args.demo:
        answers = {q.key: 3 for q in QUESTIONS}
    else:
        raw = json.loads(args.answers_json.read_text(encoding="utf-8"))
        answers = {}
        for q in QUESTIONS:
            if q.key not in raw:
                print(f"不足キー: {q.key}", file=sys.stderr)
                return 2
            v = int(raw[q.key])
            if v not in {1, 2, 3, 4, 5}:
                print(f"不正な値 {q.key}={v}", file=sys.stderr)
                return 2
            answers[q.key] = v

    soul_scores = score_answers(answers)
    best_key = pick_type(soul_scores)
    st = SOUL_TYPES[best_key]
    soul_re, phase_s, navi_s = score_diagnosis(answers, QUESTIONS, tuple(SOUL_TYPES.keys()))
    position_profile = build_position_profile(
        phase_scores=phase_s,
        navi_scores=navi_s,
        soul_scores=soul_re,
        best_key=best_key,
        soul_types=SOUL_TYPES,
        type_priority=SOUL_TYPE_PRIORITY,
    )
    theme_scores = score_themes(answers, QUESTIONS)
    manuscript = build_manuscript_insight(
        phase_key=str(position_profile.get("phase_key") or ""),
        best_type_key=best_key,
        theme_scores=theme_scores,
    )

    parts = build_strings_for_mini_summary(
        answers=answers,
        questions=QUESTIONS,
        likert_choices=LIKERT_CHOICES,
        best_key=best_key,
        soul_types=SOUL_TYPES,
        soul_type_priority=SOUL_TYPE_PRIORITY,
        position_profile=position_profile,
        manuscript_insight=manuscript,
        soul_scores=soul_scores,
        challenge_note=(args.challenge or "").strip(),
    )

    print("--- 入力サマリ（タイプ） ---", file=sys.stderr)
    print(st.name, best_key, file=sys.stderr)
    print(file=sys.stderr)

    try:
        text = generate_mini_diagnosis_summary(**parts, max_tokens=args.max_tokens)
    except MiniSummaryError as e:
        print(str(e), file=sys.stderr)
        return 1

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
