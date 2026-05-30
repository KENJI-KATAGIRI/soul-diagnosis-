from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from lib.consciousness_mapper import map_type_scores_to_consciousness
from lib.diagnosis_axes import build_position_profile, score_diagnosis
from lib.diagnosis_manuscript import build_manuscript_insight, score_themes
from lib.diagnosis_templates import SIMPLE_RESULT_TEMPLATES, build_type_result
from lib.mini_diagnosis_summary import build_strings_for_mini_summary, generate_mini_diagnosis_summary
from lib.diagnosis_email import (
    format_diagnosis_result_minimal_fallback,
    format_diagnosis_result_plain_text,
    is_diagnosis_result_email_enabled,
)
from lib.followup_automation import enqueue_followup, mark_state, process_pending_followups
from lib.premium_report import generate_premium_ai_report

from soul_nav_ai.engine import openai_client_or_none, process_turn
from soul_nav_ai.flow import FlowPhase, next_phase, session_flow_steps
from soul_nav_ai.memory import (
    append_turn,
    compare_with_previous,
    load_session,
    new_session,
    save_session,
    utc_now_iso,
)

from nav_diagnosis_ai.blueprint import SESSION_KEY as NAV_DIAG_AI_SESSION_KEY, nav_diagnosis_ai_bp
from line_seo_webhook import line_seo_bp
from nav_diagnosis_ai.load_questions import load_questionnaire
from nav_diagnosis_ai.result_logic import QuizResult, compute_result

from lib.utage_integration import (
    append_lead_log,
    build_utage_payload,
    post_utage_lead,
    validate_lead_form,
)

from lib.lec_column_articles import (
    LEC_COLUMN_ENTRIES,
    lec_column_by_slug as _lec_column_by_slug,
    lec_column_entries_english_live,
    lec_column_has_english,
)
from lib.gaia_insights_articles import (
    GAIA_INSIGHT_ARTICLES,
    gaia_insight_by_slug,
    gaia_insights_planned,
    gaia_insights_sorted,
)
from lib.gaia_jp_insights_articles import (
    GAIA_JP_LEC_BLOG_REDIRECT_SLUGS,
    gaia_jp_insight_by_slug,
    gaia_jp_insights_sorted,
)

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]


def _openai_runtime_ready() -> bool:
    """本格レポート生成に必要な OpenAI（API キー + SDK インポート）が揃っているか。"""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return False
    try:
        from openai import OpenAI  # noqa: F401

        return True
    except Exception:
        return False


def _soul_nav_min_user_chars() -> int:
    """魂のナビAIの1ターンあたりのユーザー入力の最小文字数。0 で無効（検証しない）。"""
    raw = os.environ.get("SOUL_NAV_MIN_USER_CHARS", "60").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 60


def _education_video_title() -> str:
    return os.environ.get("EDUCATION_VIDEO_TITLE", "").strip() or "診断の見方と、魂のナビ講座が必要な理由"


def _education_video_url() -> str:
    return os.environ.get("EDUCATION_VIDEO_URL", "").strip()


def _education_video_embed_url() -> str:
    return os.environ.get("EDUCATION_VIDEO_EMBED_URL", "").strip()


_DEFAULT_LINE_REGISTER_URL = "https://lp.tamashiinavi.com/p/line"
_DEFAULT_CLOSING_COURSE_VIDEO_URL = "https://lp.tamashiinavi.com/p/douga"
_DEFAULT_DIAGNOSIS_LINE_FUNNEL_URL = _DEFAULT_LINE_REGISTER_URL
_DEFAULT_PRIVACY_POLICY_URL = "https://lp.tamashiinavi.com/p/polisy"
_DEFAULT_TOKUSHO_URL = "https://lp.tamashiinavi.com/p/tokusyo"
_DEFAULT_COMPANY_URL = "https://lp.tamashiinavi.com/p/co"
_DEFAULT_SOUL_COURSE_NORMAL_URL = "https://lp.tamashiinavi.com/p/normal"
_DEFAULT_SOUL_COURSE_EARLY_URL = "https://lp.tamashiinavi.com/p/first"
_DEFAULT_SOUL_COURSE_THANKS_URL = "https://lp.tamashiinavi.com/p/thanx"

_UNSUBSCRIBE_FILE = Path(__file__).resolve().parent / "data" / "unsubscribed_emails.json"


def _load_unsubscribe_set() -> set:
    try:
        if _UNSUBSCRIBE_FILE.exists():
            return set(json.loads(_UNSUBSCRIBE_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return set()


def _add_to_unsubscribe(email: str) -> None:
    s = _load_unsubscribe_set()
    s.add(email.strip().lower())
    _UNSUBSCRIBE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _UNSUBSCRIBE_FILE.write_text(json.dumps(sorted(s), ensure_ascii=False, indent=2), encoding="utf-8")


def _is_email_unsubscribed(email: str) -> bool:
    return email.strip().lower() in _load_unsubscribe_set()


def _closing_course_video_url() -> str:
    """診断レポート直後の講座クロージング動画（Utage 等）。空文字で無効化。"""
    v = os.environ.get("CLOSING_COURSE_VIDEO_URL")
    if v is not None:
        return v.strip()
    return _DEFAULT_CLOSING_COURSE_VIDEO_URL


def _closing_course_video_embed_url() -> str:
    raw = os.environ.get("CLOSING_COURSE_VIDEO_EMBED_URL")
    if raw is not None and raw.strip():
        return raw.strip()
    return _closing_course_video_url()


def _closing_course_video_title() -> str:
    return os.environ.get("CLOSING_COURSE_VIDEO_TITLE", "").strip() or "あなたの傾向の整え方"


def _diagnosis_result_email_delay_minutes() -> int:
    """診断結果メールをキューに積むまでの遅延（分）。0 以下は即送信になり導線が切れるため既定5分に寄せる。"""
    raw = os.environ.get("DIAG_RESULT_EMAIL_DELAY_MIN", "5").strip()
    try:
        n = int(raw)
    except ValueError:
        return 5
    if n <= 0:
        return 5
    return min(n, 7 * 24 * 60)


def _line_register_url() -> str:
    """LINE公式アカウント登録URL（UTAGE管理画面から取得したもの）。空文字でLINE誘導を非表示。"""
    return os.environ.get("LINE_REGISTER_URL", "").strip() or _DEFAULT_LINE_REGISTER_URL


def _diagnosis_line_funnel_url() -> str:
    """診断レポート直後の次ステップ（UTAGE 内 LINE 登録ページ等）。未設定時は既定のファネルURL。"""
    return os.environ.get("DIAGNOSIS_LINE_FUNNEL_URL", "").strip() or _DEFAULT_DIAGNOSIS_LINE_FUNNEL_URL


def _diagnosis_line_funnel_title() -> str:
    return os.environ.get("DIAGNOSIS_LINE_FUNNEL_TITLE", "").strip() or "LINE登録後に、整え方の動画を受け取る"


def _privacy_policy_url() -> str:
    return os.environ.get("PRIVACY_POLICY_URL", "").strip() or _DEFAULT_PRIVACY_POLICY_URL


def _tokusho_url() -> str:
    return os.environ.get("TOKUSHO_URL", "").strip() or _DEFAULT_TOKUSHO_URL


def _company_url() -> str:
    return os.environ.get("COMPANY_URL", "").strip() or _DEFAULT_COMPANY_URL


@dataclass(frozen=True)
class SoulType:
    key: str
    name: str
    summary: str
    strengths: List[str]
    pitfalls: List[str]
    next_actions: List[str]


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    axis_weights: Dict[str, int]
    theme_weights: Dict[str, int] = field(default_factory=dict)


SOUL_TYPES: Dict[str, SoulType] = {
    "intuition_navi": SoulType(
        key="intuition_navi",
        name="直感ナビ型",
        summary="感覚で未来の方向性をつかむタイプ。ひらめきやサインを受け取りながら進むことで、本来の流れに乗りやすいスタイルです。",
        strengths=[
            "直感で本質を見抜きやすい",
            "タイミングや流れを読むのが得意",
            "新しい可能性をいち早く感じ取れる",
        ],
        pitfalls=[
            "ひらめきを言葉にする前に動いてしまい、周りに伝わりにくいことがある",
            "気分や状況に左右されて、決断を後回しにしてしまうことがある",
            "根拠を求められたときに、自信をなくしやすい",
        ],
        next_actions=[
            "最近ピンと来ている方向性を1つだけ選び、「なぜ惹かれるのか」を3行で言葉にしてみる",
            "『本当はこうしたい』と思っていることを、信頼できる人に1つだけシェアしてみる",
            "直感で決めたいことほど、締切日を先に決めておき、その日までは情報収集と整理だけに集中してみる",
        ],
    ),
    "strategy_thinker": SoulType(
        key="strategy_thinker",
        name="戦略思考型",
        summary="構造や仕組みから未来を組み立てるタイプ。全体像を描き、最適な道筋を考えることで、現実を着実に動かしていくスタイルです。",
        strengths=[
            "物事を整理し、分かりやすく構造化できる",
            "ゴールから逆算して計画を立てるのが得意",
            "リスクや優先順位を冷静に判断できる",
        ],
        pitfalls=[
            "情報や選択肢が増えるほど、考えすぎて動き出しが遅くなりやすい",
            "完璧な計画を求めすぎて、小さな一歩を軽く見てしまうことがある",
            "頭での正解を優先するあまり、本音や感情を後回しにしがち",
        ],
        next_actions=[
            "今抱えているテーマについて、『3か月後どうなっていたいか』をA4一枚でラフに書き出してみる",
            "そのゴールに向けた“最初の一歩”を15分以内で終わる行動に分解し、今日中に着手してみる",
            "情報収集する日は『調べるだけの日』と決め、翌日に『決める日』をあらかじめカレンダーに入れておく",
        ],
    ),
    "action_breakthrough": SoulType(
        key="action_breakthrough",
        name="行動突破型",
        summary="動きながら道を作っていくタイプ。スピードと実行力で停滞を突破し、周りの空気ごと前に進めていくスタイルです。",
        strengths=[
            "思いついたことをすぐ形にできる",
            "多少のプレッシャーがあっても前進し続けられる",
            "周りの人の背中を押し、場のエネルギーを引き上げられる",
        ],
        pitfalls=[
            "走りながら考える分、方向がズレていることに気づきにくい",
            "一人で抱え込みすぎて、疲れに気づくのが遅くなりやすい",
            "「止まる＝負け」のように感じて、必要な休憩を後回しにしてしまう",
        ],
        next_actions=[
            "今進めていることの中で『一番結果を出したいこと』を1つに絞り、残りは一度“保留リスト”に移してみる",
            "一日の終わりに、『今日の行動の中で、特に意味があった3つ』だけをメモして、そこから見える共通点を探してみる",
            "次の7日間だけ、『走る日』と『整える日』を交互に入れ、あえて何もしない日もスケジュールに確保してみる",
        ],
    ),
    "harmony_leader": SoulType(
        key="harmony_leader",
        name="調和リーダー型",
        summary="人と場の関係性の中で力を発揮するタイプ。安心できる空気をつくりながら、全体が前に進めるように調整していくスタイルです。",
        strengths=[
            "相手の気持ちや場の空気を敏感に感じ取れる",
            "対立を和らげ、みんなが話しやすい場をつくれる",
            "一人ひとりの立場を尊重しつつ、全体として進める方向を見つけられる",
        ],
        pitfalls=[
            "周りを優先するあまり、自分の本音や希望を後回しにしてしまいがち",
            "誰にも迷惑をかけたくなくて、一人で抱え込みやすい",
            "決断の場面で「みんなの気持ち」を気にしすぎて、進み出すタイミングを逃しやすい",
        ],
        next_actions=[
            "最近の出来事の中で『本当はこうしたかった』ことを3つ書き出し、そのうち1つだけ誰かに正直に伝えてみる",
            "会議や話し合いの最後に、『今日決まったこと』『まだ決めなくていいこと』を1分でまとめて口に出してみる",
            "一週間に一度、“自分のためだけの予定”を1〜2時間分カレンダーに入れ、その時間だけは誰の期待も背負わないと決めて過ごしてみる",
        ],
    ),
}


QUESTIONS: List[Question] = [
    Question(
        key="q1",
        text="迷ったとき、まず『直感』や“なんとなく”の感覚を大事にして選ぶことが多い。",
        axis_weights={"intuition_navi": 2, "action_breakthrough": 1},
    ),
    Question(
        key="q2",
        text="新しいことを始める前に、目的や手順、リスクをできるだけ整理してから動きたいほうだ。",
        axis_weights={"strategy_thinker": 2},
    ),
    Question(
        key="q3",
        text="考え続けるより、まず動いてみて、その結果を見ながら調整していくほうがしっくりくる。",
        axis_weights={"action_breakthrough": 2},
    ),
    Question(
        key="q4",
        text="人の気持ちや場の空気を自然と感じ取り、その場がうまく回るように動くことが多い。",
        axis_weights={"harmony_leader": 2},
    ),
    Question(
        key="q5",
        text="はっきりした理由はないのに『こっちのほうが良さそう』と感じて、その感覚に従って動いた経験がある。",
        axis_weights={"intuition_navi": 2},
    ),
    Question(
        key="q6",
        text="物事の仕組みやパターン、因果関係を考えるのが好きで、『なぜそうなるか』を理解したくなる。",
        axis_weights={"strategy_thinker": 2},
    ),
    Question(
        key="q7",
        text="停滞している状況や、誰も決めない状態を見ると、『とにかく一歩進めよう』と動きたくなる。",
        axis_weights={"action_breakthrough": 2, "harmony_leader": 1},
    ),
    Question(
        key="q8",
        text="対立しそうな場面や、意見がぶつかり合う場面で、間に入って調整役になることが多い。",
        axis_weights={"harmony_leader": 2},
    ),
    Question(
        key="q9",
        text="未来のイメージやひらめきが先に浮かび、それを現実に落とし込む方法をあとから考えることがよくある。",
        axis_weights={"intuition_navi": 2, "strategy_thinker": 1},
    ),
    Question(
        key="q10",
        text="みんなが気持ちよく動けるように役割分担や段取りを考えたり、話し合いの場を整えたりするのが得意だと感じる。",
        axis_weights={"harmony_leader": 2, "strategy_thinker": 1},
    ),
    # --- q11〜q20：講座理論の観測軸（体感・時間耐性・フェーズ・心/魂ナビ）---
    Question(
        key="q11",
        text="「正しい理由」は揃っているのに、考え込むほど息が浅くなったり胸が重くなったりしやすい。",
        axis_weights={"navi_mind": 2, "strategy_thinker": 1},
    ),
    Question(
        key="q12",
        text="決める前に「失敗したらどうしよう」「どう取り繕うか」が先に強く浮かびやすい。",
        axis_weights={"navi_mind": 2},
    ),
    Question(
        key="q13",
        text="小さな選択でも、体の軽さ・重さや呼吸の深浅を手がかりにしたいと感じる。",
        axis_weights={"navi_soul": 2, "intuition_navi": 1},
    ),
    Question(
        key="q14",
        text="本当に大事な直感や方向性は、時間が経っても静かに残りやすい（すぐには消えない）。",
        axis_weights={"navi_soul": 2, "intuition_navi": 1},
    ),
    Question(
        key="q15",
        text="周囲からは順調に見えるのに、内側では満たされなさや「まだ違う」が消えにくい。",
        axis_weights={"phase_sway": 2, "harmony_leader": 1},
    ),
    Question(
        key="q16",
        text="以前は問題なく続けられていたことが、急にしんどくなった経験がある。",
        axis_weights={"phase_sway": 2},
    ),
    Question(
        key="q17",
        text="何を選ぶかより、「自分の基準そのものが揺れている」感覚に近い時期がある。",
        axis_weights={"phase_sway": 1, "phase_void": 1},
    ),
    Question(
        key="q18",
        text="価値観・役割・関係の枠組みが大きく変わった／手放しが起きた感覚がある。",
        axis_weights={"phase_collapse": 2},
    ),
    Question(
        key="q19",
        text="深く考えたくない日が続く、情報に飽きる、決断を先延ばしにしたくなる時期がある。",
        axis_weights={"phase_void": 2},
    ),
    Question(
        key="q20",
        text="ズレたまま進むと、体や感覚が強く拒否するようになってきた（整えないと進みにくい）。",
        axis_weights={"phase_integration": 2, "action_breakthrough": 1},
    ),
    # --- q21〜q30：書籍原稿（第1〜5章）に沿った補強（使命・統合・自己責め・情報過多など）---
    Question(
        key="q21",
        text="迷ったとき、すぐに「努力が足りない」「覚悟が足りない」と自分を責めてしまいやすい。",
        axis_weights={"navi_mind": 2, "phase_sway": 1},
        theme_weights={"theme_self_blame": 2},
    ),
    Question(
        key="q22",
        text="情報を集めれば集めるほど、かえって一歩が踏み出せなくなることがある。",
        axis_weights={"strategy_thinker": 2, "navi_mind": 1},
        theme_weights={"theme_info_paralysis": 2},
    ),
    Question(
        key="q23",
        text="進みたい気持ちと、怖さや止めたい気持ちが同時に強く出て、引っ張り合いを感じることがある。",
        axis_weights={"harmony_leader": 1, "action_breakthrough": 1, "intuition_navi": 1, "phase_sway": 1},
        theme_weights={"theme_inner_conflict": 2},
    ),
    Question(
        key="q24",
        text="やめようとしても、同じテーマや関心に何度も戻ってしまう。",
        axis_weights={"intuition_navi": 2, "navi_soul": 1},
        theme_weights={"theme_recurring_pull": 2},
    ),
    Question(
        key="q25",
        text="使命や天職を「外側に正解があるもの」として探し続けてしまう。",
        axis_weights={"navi_mind": 2, "strategy_thinker": 1},
        theme_weights={"theme_mission_external": 2},
    ),
    Question(
        key="q26",
        text="不安や揺れているときほど、早く結論を出そうとしてしまう。",
        axis_weights={"action_breakthrough": 1, "navi_mind": 1, "phase_sway": 1},
        theme_weights={"theme_rush_conclusion": 2},
    ),
    Question(
        key="q27",
        text="体や気持ちに限界のサインがあっても、「まだ頑張れる」と自分を鼓舞して踏みとどまりがち。",
        axis_weights={"navi_mind": 2, "action_breakthrough": 1, "phase_collapse": 1},
        theme_weights={"theme_override_limits": 2},
    ),
    Question(
        key="q28",
        text="頭では納得や理解があるのに、日常の選び方は以前とあまり変わらないと感じることがある。",
        axis_weights={"navi_mind": 2, "phase_sway": 1},
        theme_weights={"theme_head_body_gap": 2},
    ),
    Question(
        key="q29",
        text="体感で気づいた方向より、正しさや安全のほうを選んでしまうことが多い。",
        axis_weights={"navi_mind": 2, "harmony_leader": 1},
        theme_weights={"theme_safety_over_felt": 2},
    ),
    Question(
        key="q30",
        text="「わかったのにまた戻る」自分を見て、意志が弱いと責めてしまう。",
        axis_weights={"navi_mind": 2, "phase_sway": 1},
        theme_weights={"theme_willpower_shame": 2},
    ),
]

SOUL_TYPE_PRIORITY: List[str] = [
    "intuition_navi",
    "strategy_thinker",
    "action_breakthrough",
    "harmony_leader",
]


LIKERT_CHOICES: List[Tuple[int, str]] = [
    (1, "まったく当てはまらない"),
    (2, "あまり当てはまらない"),
    (3, "どちらともいえない"),
    (4, "やや当てはまる"),
    (5, "とても当てはまる"),
]

CHALLENGE_NOTE_MAX_LEN = 2000
DIAGNOSIS_CHALLENGE_FIELD = "challenge_note"


def _display_scores_from_hidden_form(form) -> List[Tuple[str, int]]:
    """診断結果フォームから渡す score_N=name::value をパースする。"""
    out: List[Tuple[str, int]] = []
    for i in range(4):
        raw = form.get(f"score_{i}", "").strip()
        if raw and "::" in raw:
            name, val = raw.split("::", 1)
            try:
                out.append((name.strip(), int(val.strip())))
            except ValueError:
                pass
    return out


def _resolve_best_key_from_form(form, display_scores: List[Tuple[str, int]]) -> Optional[str]:
    best_key = form.get("best_key", "").strip()
    if best_key in SOUL_TYPES:
        return best_key
    if not display_scores:
        return None
    top_name = max(display_scores, key=lambda x: x[1])[0]
    for k, st in SOUL_TYPES.items():
        if st.name == top_name:
            return k
    return None


def _premium_reports_dir() -> Path:
    root = Path(__file__).resolve().parent / "data" / "premium_reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lec_inquiries_file() -> Path:
    root = Path(__file__).resolve().parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "lec_inquiries.jsonl"



def _lec_blocked_ips() -> set:
    p = Path(__file__).resolve().parent / "data" / "lec_blocked_ips.txt"
    if not p.exists():
        return set()
    result = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            result.add(line)
    return result


def _lec_blocked_names() -> set:
    p = Path(__file__).resolve().parent / "data" / "lec_blocked_names.txt"
    if not p.exists():
        return set()
    result = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            result.add(line)
    return result


def _lec_rate_limited(ip: str) -> bool:
    import datetime
    LIMIT = 3
    try:
        filepath = _lec_inquiries_file()
        if not filepath.exists():
            return False
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        ip_norm = ip.split(",")[0].strip()
        count = 0
        with filepath.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("created_at", "")
                    created = datetime.datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    if created < cutoff:
                        continue
                    if entry.get("ip", "").split(",")[0].strip() == ip_norm:
                        count += 1
                except Exception:
                    continue
        return count >= LIMIT
    except Exception:
        return False



# ── スパム自動検知 ──────────────────────────────────────────────────────────

# 「値段を聞く」スパムで使われる多言語キーワード
_SPAM_PRICE_PATTERNS = [
    "wanted to know your price", "want to know your price",
    "wollte ihren preis", "votre prix", "uw prijs", "su precio",
    "quería saber", "quero saber", "cena", "preis wissen",
    "знать цену", "цену", "bilmek istedim", "qiymət",
    "muốn biết giá", "kumukūʻai", "makemake wau",
    "ọnụahịa", "achọrọ m", "theastaigh uaim", "dia duit",
    "htio sam znati", "meg akartam", "árát", "çmimin",
    "gribēju zināt", "vēlējos uzzināt",
]

def _lec_spam_score(name: str, email: str, phone: str, message: str, ip: str) -> int:
    """
    スパムスコアを返す（0〜100）。60以上でスパム判定。
    複数の要素を組み合わせて誤検知を減らす。
    """
    import re
    score = 0
    msg_lower = message.lower()

    # 短いメッセージ（本物のお問い合わせはたいてい長い）
    if len(message) < 80:
        score += 25
    if len(message) < 40:
        score += 15  # 追加

    # 価格問い合わせスパムパターン
    for pattern in _SPAM_PRICE_PATTERNS:
        if pattern in msg_lower:
            score += 40
            break

    # 日本語・英語・韓国語以外の文字を使った短いメッセージ（多言語バラまき型）
    jp_chars = len(re.findall(r"[\u3040-\u30ff\u4e00-\u9fff]", message))
    if jp_chars == 0 and len(message) < 100:
        score += 10

    # 電話番号が異常に長い（偽物）
    digits_only = re.sub(r"[^0-9]", "", phone)
    if len(digits_only) > 12:
        score += 20

    # IPが既知のスパム送信元 /24 帯
    ip_norm = ip.split(",")[0].strip()
    if ip_norm.startswith("80.94.95."):
        score += 30

    return min(score, 100)


def _lec_quarantine(payload: dict, score: int) -> None:
    """スパム判定された送信をクォランティンファイルに保存し、LINE通知する。"""
    import urllib.request as urlreq
    p = Path(__file__).resolve().parent / "data" / "lec_quarantine.jsonl"
    payload["spam_score"] = score
    try:
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # IPが繰り返しスパムを送っていたら自動でブロックリストに追加
    _lec_auto_block_ip(payload.get("ip", "").split(",")[0].strip())

    # LINE通知（line_hair_token.txt を流用）
    try:
        token_path = Path("/home/ubuntu/.secrets/line_hair_token.txt")
        owner_path = Path("/home/ubuntu/.secrets/owner_line_id.txt")
        if not token_path.exists() or not owner_path.exists():
            return
        token = token_path.read_text().strip()
        owner = owner_path.read_text().strip()
        msg = (
            f"🚨 スパム検知 (score={score})\n"
            f"名前: {payload.get('name','')}\n"
            f"IP: {payload.get('ip','')}\n"
            f"メール: {payload.get('email','')}\n"
            f"本文: {payload.get('message','')[:60]}"
        )
        body = json.dumps({"to": owner, "messages": [{"type": "text", "text": msg}]})
        req = urlreq.Request(
            "https://api.line.me/v2/bot/message/push",
            data=body.encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        urlreq.urlopen(req, timeout=5)
    except Exception:
        pass


def _lec_auto_block_ip(ip: str) -> None:
    """クォランティンに同一IPが3件以上あったら自動でIPブロックリストに追加する。"""
    if not ip:
        return
    try:
        q_path = Path(__file__).resolve().parent / "data" / "lec_quarantine.jsonl"
        block_path = Path(__file__).resolve().parent / "data" / "lec_blocked_ips.txt"
        if not q_path.exists():
            return
        count = sum(
            1 for line in q_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("ip", "").split(",")[0].strip() == ip
        )
        if count >= 3:
            existing = block_path.read_text(encoding="utf-8") if block_path.exists() else ""
            if ip not in existing:
                with block_path.open("a", encoding="utf-8") as f:
                    f.write(f"{ip}\n")
    except Exception:
        pass


def _send_lec_notify_email(name: str, email: str, phone: str, lang: str, message: str) -> None:
    """Send notification email to admin when a LEC inquiry is received."""
    import smtplib
    from email.message import EmailMessage

    notify_to = os.environ.get("LEC_NOTIFY_EMAIL", "kenji.kys@gmail.com").strip()
    host = os.environ.get("SMTP_HOST", "").strip()
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not host or not from_email:
        return

    from_name = os.environ.get("LEC_FROM_NAME", "").strip() or "Life Energy Coaching"
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()

    subject = f"\U0001F514\U0001F31F\u3010LEC\u304A\u554F\u5408\u305B\u3011{name} \u69D8\u3088\u308A\u65B0\u898F\u304A\u554F\u5408\u305B \U0001F31F"
    sep = "\u2501" * 30
    phone_disp = phone if phone else "\u306A\u3057"
    lang_disp = lang if lang else "\u672A\u6307\u5B9A"
    body = (
        f"{sep}\n"
        "\U0001F514 Life Energy Coaching \u65B0\u898F\u304A\u554F\u5408\u305B\n"
        f"{sep}\n\n"
        f"\U0001F464 \u304A\u540D\u524D: {name}\n"
        f"\U0001F4E7 \u30E1\u30FC\u30EB: {email}\n"
        f"\U0001F4DE \u96FB\u8A71: {phone_disp}\n"
        f"\U0001F310 \u5E0C\u671B\u8A00\u8A9E: {lang_disp}\n\n"
        f"{sep}\n"
        "\U0001F4DD \u304A\u554F\u5408\u305B\u5185\u5BB9:\n"
        f"{sep}\n\n"
        f"{message}\n\n"
        f"{sep}\n"
        f"\u203B \u3053\u306E\u30E1\u30FC\u30EB\u306F\u81EA\u52D5\u901A\u77E5\u3067\u3059\u3002\u76F4\u63A5 {email} \u3078\u3054\u8FD4\u4FE1\u304F\u3060\u3055\u3044\u3002\n"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = notify_to
    msg["Reply-To"] = email
    msg.set_content(body)

    use_ssl = os.environ.get("SMTP_USE_SSL", "").strip() == "1"
    use_starttls = os.environ.get("SMTP_USE_STARTTLS", "1").strip() != "0"
    port = int(os.environ.get("SMTP_PORT", "587").strip() or "587")

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                if smtp_user:
                    s.login(smtp_user, smtp_pass)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                if use_starttls:
                    s.starttls()
                    s.ehlo()
                if smtp_user:
                    s.login(smtp_user, smtp_pass)
                s.send_message(msg)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("LEC notify email failed")


def _save_premium_report_file(report_id: str, data: Dict[str, object]) -> None:
    p = _premium_reports_dir() / f"{report_id}.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_premium_report_file(report_id: str) -> Optional[Dict[str, object]]:
    p = _premium_reports_dir() / f"{report_id}.json"
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _delete_premium_report_file(report_id: Optional[str]) -> None:
    if not report_id:
        return
    p = _premium_reports_dir() / f"{report_id}.json"
    if p.is_file():
        try:
            p.unlink()
        except OSError:
            pass


def _clear_premium_session() -> None:
    rid = session.pop("premium_report_id", None)
    session.pop("premium_unlocked", None)
    session.pop("last_soul_nav_session_id", None)
    session.pop("soul_nav_prefilled_turn", None)
    _delete_premium_report_file(rid if isinstance(rid, str) else None)


def _qa_lines_from_session(answers: Dict[str, int]) -> List[str]:
    lines: List[str] = []
    for q in QUESTIONS:
        val = answers.get(q.key)
        if val is None:
            continue
        label = next((lab for v, lab in LIKERT_CHOICES if v == val), str(val))
        lines.append(f"- {q.text} → {val}（{label}）")
    return lines


def _int_answers_from_request_form(form) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for q in QUESTIONS:
        raw = form.get(q.key, "").strip()
        if not raw:
            continue
        try:
            v = int(raw)
        except ValueError:
            continue
        if v in {1, 2, 3, 4, 5}:
            out[q.key] = v
    return out


def _quiz_complete(answers: Dict[str, int]) -> bool:
    return all(q.key in answers for q in QUESTIONS)


def _merge_ten_quiz_snapshot(ctx: Dict[str, object], answers: Optional[Dict[str, int]]) -> None:
    if not answers or not _quiz_complete(answers):
        return
    ctx["ten_quiz_snapshot"] = "\n".join(_qa_lines_from_session(answers))


def _bundle_user_text_for_soul_nav(
    focus: str,
    free_text: str,
    challenge_note: str = "",
) -> str:
    """深掘りパック：レポート生成フォームと同じ入力を、魂のナビ1ターン目にも流用する。"""
    parts: List[str] = []
    if focus.strip():
        parts.append(focus.strip())
    if free_text.strip():
        parts.append(free_text.strip())
    if parts:
        return "\n\n".join(parts).strip()
    return str(challenge_note or "").strip()


def _funnel_for_soul_nav(rec: Optional[object]) -> Tuple[int, int]:
    """魂のナビ画面用ファネル表示（完了段数・強調段）。"""
    if rec is None:
        return 0, 3
    ctx = getattr(rec, "soul_type_context", None)
    if isinstance(ctx, dict) and ctx.get("premium_linked"):
        return 3, 4
    return 2, 3


def _quiz_from_flask_session() -> Optional[Dict[str, int]]:
    raw = session.get("type_quiz_answers")
    if not isinstance(raw, dict):
        return None
    out: Dict[str, int] = {}
    for q in QUESTIONS:
        v = raw.get(q.key)
        try:
            if v is not None:
                out[q.key] = int(v)
        except (TypeError, ValueError):
            return None
    return out if _quiz_complete(out) else None


def _soul_type_context_for_nav(best_key: str, display_scores: List[Tuple[str, int]]) -> Dict[str, object]:
    st = SOUL_TYPES[best_key]
    return {
        "type_key": st.key,
        "type_name": st.name,
        "summary": st.summary,
        "scores_by_name": {n: s for n, s in display_scores},
        "strengths": list(st.strengths),
        "pitfalls": list(st.pitfalls),
    }


def _premium_coaching_brief_from_report(report: Dict[str, object], max_chars: int = 4200) -> str:
    """魂のナビAI に渡すレポート要約（フル再掲はせず圧縮）。"""
    chunks: List[str] = []
    for label, key in (
        ("全体像", "opening"),
        ("タイプ深掘り", "type_in_depth"),
        ("ナビの地図", "navigation_map"),
        ("いまの見立て", "problem"),
        ("背景", "cause"),
        ("このままの場合", "if_unchanged"),
        ("進んだとき", "with_course"),
        ("今週の一歩", "this_week_action"),
    ):
        v = report.get(key)
        if isinstance(v, str) and v.strip():
            chunks.append(f"【{label}】\n{v.strip()}")
    na = report.get("next_actions")
    if isinstance(na, list) and na:
        lines = [f"- {x}" for x in na if isinstance(x, str) and x.strip()]
        if lines:
            chunks.append("【レポートで提案された次のアクション】\n" + "\n".join(lines))
    cl = report.get("closing")
    if isinstance(cl, str) and cl.strip():
        chunks.append(f"【締め】\n{cl.strip()}")
    text = "\n\n".join(chunks)
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n（以下略）"
    return text


def _soul_nav_context_with_premium(
    best_key: str,
    display_scores: List[Tuple[str, int]],
    report: Dict[str, object],
) -> Dict[str, object]:
    ctx = dict(_soul_type_context_for_nav(best_key, display_scores))
    ctx["premium_linked"] = True
    ctx["premium_coaching_brief"] = _premium_coaching_brief_from_report(report)
    ctx["suggested_opener"] = (
        "本格レポートで一番しっくりきた箇所と、いま一番引っかかっている一点を、短く書いてみてください。"
    )
    _merge_ten_quiz_snapshot(ctx, _quiz_from_flask_session())
    return ctx


def _display_scores_from_flask_session() -> Optional[List[Tuple[str, int]]]:
    best_key = session.get("type_quiz_best_key")
    if not isinstance(best_key, str) or best_key not in SOUL_TYPES:
        return None
    raw_scores = session.get("type_quiz_scores_by_key")
    scores_by_key: Dict[str, int] = {}
    if isinstance(raw_scores, dict):
        for k, v in raw_scores.items():
            if isinstance(k, str):
                try:
                    scores_by_key[k] = int(v)
                except (TypeError, ValueError):
                    pass
    if not scores_by_key:
        answers = session.get("type_quiz_answers")
        if isinstance(answers, dict):
            int_answers: Dict[str, int] = {}
            for q in QUESTIONS:
                v = answers.get(q.key)
                try:
                    if v is not None:
                        int_answers[q.key] = int(v)
                except (TypeError, ValueError):
                    pass
            if len(int_answers) == len(QUESTIONS):
                scores_by_key = score_answers(int_answers)
    if not scores_by_key:
        return None
    sorted_scores = sorted(scores_by_key.items(), key=lambda kv: kv[1], reverse=True)
    return [(SOUL_TYPES[k].name, v) for k, v in sorted_scores if k in SOUL_TYPES]


def _nav_diagnosis_result_from_session() -> Optional[QuizResult]:
    raw = session.get(NAV_DIAG_AI_SESSION_KEY)
    if not isinstance(raw, dict):
        return None
    answers = raw.get("answers")
    if not isinstance(answers, dict):
        return None
    qz = load_questionnaire()
    for q in qz.questions:
        qid = str(q.get("id") or "").strip()
        if not qid or qid not in answers:
            return None
    try:
        return compute_result(answers, qz.questions)
    except Exception:
        return None


def _latest_soul_nav_output(rec: Optional[object]) -> Optional[Dict[str, Any]]:
    if rec is None:
        return None
    turns = getattr(rec, "turns", None)
    if not isinstance(turns, list) or not turns:
        return None
    last = turns[-1]
    if not isinstance(last, dict):
        return None
    out = last.get("output")
    if not isinstance(out, dict):
        return None
    need = ("state_organization", "discrepancy", "yesno_hypothesis", "aligned_action", "followup_question")
    for k in need:
        if not isinstance(out.get(k), str) or not str(out.get(k)).strip():
            return None
    return out


def _integration_sheet_payload(
    nav_result: QuizResult,
    soul_output: Dict[str, Any],
    session_id: str,
) -> Dict[str, Any]:
    merged_alignment = nav_result.alignment_state
    soul_discrepancy = str(soul_output.get("discrepancy") or "")
    if "一致" in soul_discrepancy and "ズレ" not in soul_discrepancy:
        merged_alignment = "一致状態"
    elif "ズレ" in soul_discrepancy and "一致" not in soul_discrepancy:
        merged_alignment = "受信しているが迷っている状態"

    return {
        "title": "統合1枚レポート",
        "subtitle": "診断AI（構造化）× 魂のナビAI（対話）を1枚に統合",
        "current_state": merged_alignment,
        "nav_verdict": nav_result.verdict_label,
        "nav_focus": nav_result.theme,
        "nav_state": nav_result.current_state,
        "consciousness_level": nav_result.consciousness_level,
        "consciousness_label": nav_result.consciousness_label,
        "consciousness_emotion": nav_result.consciousness_emotion,
        "consciousness_position": nav_result.consciousness_position,
        "energy_score": nav_result.energy_score,
        "alignment_state": nav_result.alignment_state,
        "misalignment_reason": nav_result.misalignment_reason,
        "body_signal_summary": nav_result.body_signal_summary,
        "future_if_aligned": nav_result.future_if_aligned,
        "next_step": nav_result.next_step,
        "nav_hypothesis": nav_result.yesno_hypothesis,
        "nav_one_liner": nav_result.one_liner,
        "soul_state_organization": str(soul_output.get("state_organization") or ""),
        "soul_discrepancy": soul_discrepancy,
        "soul_yesno": str(soul_output.get("yesno_hypothesis") or ""),
        "soul_action": str(soul_output.get("aligned_action") or ""),
        "soul_question": str(soul_output.get("followup_question") or ""),
        "unified_summary": (
            f"診断AIでは『{nav_result.alignment_state}』、意識レベルは {nav_result.consciousness_level} 付近。"
            " 魂のナビAIの対話では、言葉の整合より身体反応を優先して再検証しています。"
            " いまは『高いか低いか』ではなく『一致しているか』を軸に意思決定する段階です。"
        ),
        "session_id": session_id,
    }


def _request_hostname() -> str:
    """Host ヘッダ（ポート除く）。リクエストコンテキスト外では呼ばないこと。"""
    return (request.host or "").split(":")[0].lower()


def _is_gaia_public_host() -> bool:
    """gaiaarts.org 向けに / を Gaia 英語トップにする。"""
    return _request_hostname() in ("gaiaarts.org", "www.gaiaarts.org")


def _host_in_env_list(env_name: str, defaults: Tuple[str, ...]) -> bool:
    """カンマ区切りの環境変数でホスト名を上書き可能（本番ドメイン差し替え用）。"""
    raw = os.environ.get(env_name, "").strip()
    if raw:
        hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    else:
        hosts = set(defaults)
    return _request_hostname() in hosts


def _is_life_energy_public_host() -> bool:
    """life-energy-coaching.net 向けに / を LEC ランディング（/lec 相当）にする。"""
    return _host_in_env_list(
        "LIFE_ENERGY_ROOT_HOSTS",
        ("life-energy-coaching.net", "www.life-energy-coaching.net"),
    )


def _seo_canonical_url() -> str:
    """公開3ドメインは canonical / og:url を非 www に揃える。それ以外は request.url。"""
    h = _request_hostname()
    apex = {
        "gaiaarts.org": "gaiaarts.org",
        "www.gaiaarts.org": "gaiaarts.org",
        "tamashiinavi.com": "tamashiinavi.com",
        "www.tamashiinavi.com": "tamashiinavi.com",
        "life-energy-coaching.net": "life-energy-coaching.net",
        "www.life-energy-coaching.net": "life-energy-coaching.net",
    }.get(h)
    if not apex:
        return request.url
    return f"https://{apex}{request.path}"


def _lec_public_en_canonical(en_path: str) -> str:
    """life-energy 公開ホストで /en/... の canonical（/lec/en/ ミラー表示時も og:url は /en/... に揃える）。"""
    if not en_path.startswith("/"):
        en_path = "/" + en_path
    return f"https://life-energy-coaching.net{en_path}"


def _lec_public_jp_canonical(path: str) -> str:
    """日本語サブページの canonical（/lec/... ミラー表示時も og:url はルートパスに揃える）。"""
    if not path.startswith("/"):
        path = "/" + path
    return f"https://life-energy-coaching.net{path}"


_HAIR_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".avif"})


def _hair_salon_static_filenames_sorted() -> List[str]:
    """static/hair/ 以下の画像ファイル名（昇順）。フォルダが無ければ空。"""
    root = Path(__file__).resolve().parent / "static" / "hair"
    if not root.is_dir():
        return []
    names: List[str] = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file() and p.suffix.lower() in _HAIR_IMAGE_SUFFIXES:
            names.append(p.name)
    return names


def _hair_salon_hero_and_gallery(names: List[str]) -> Tuple[Optional[str], List[str]]:
    """先頭の hero.* / cover.* / main.* をヒーローにし、それ以外をギャラリーにする。無ければ先頭ファイルをヒーロー。"""
    if not names:
        return None, []
    hero_prefixes = ("hero.", "cover.", "main.")
    hero: Optional[str] = None
    for n in names:
        low = n.lower()
        if any(low.startswith(p) for p in hero_prefixes):
            hero = n
            break
    if hero is None:
        hero = names[0]
    gallery = [n for n in names if n != hero]
    return hero, gallery


def _hair_salon_json_ld(*, canonical_url: str, image_abs_urls: List[str]) -> Dict[str, Any]:
    """BeautySalon 用 JSON-LD（画像は任意）。"""
    data: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "BeautySalon",
        "name": "GaiaArtsHair",
        "alternateName": "GaiaArtsCreation",
        "url": canonical_url,
        "address": {
            "@type": "PostalAddress",
            "postalCode": "460-0007",
            "addressRegion": "愛知県",
            "addressLocality": "名古屋市中区",
            "streetAddress": "新栄2-29-22 ファインアート川口２D",
            "addressCountry": "JP",
        },
        "parentOrganization": {
            "@type": "Organization",
            "name": "Gaia Arts Co., Ltd.",
            "url": "https://gaiaarts.org",
        },
    }
    if image_abs_urls:
        data["image"] = image_abs_urls
    return data


def create_app() -> Flask:
    # `.env` は「カレントディレクトリ」ではなく app.py と同じディレクトリから読む。
    # Gunicorn/systemd では cwd が別になることが多く、その場合従来の load_dotenv() だと読めない。
    # override=True: このディレクトリの .env を正とする（systemd に残った古い SMTP_* より .env が優先）。
    # 例外: unit で Environment=LOAD_DOTENV_NO_OVERRIDE=1 を付けると従来どおり .env は未設定キーのみ補完。
    if load_dotenv is not None:
        _env_file = Path(__file__).resolve().parent / ".env"
        if _env_file.is_file():
            _no_override = os.environ.get("LOAD_DOTENV_NO_OVERRIDE", "").strip() == "1"
            load_dotenv(_env_file, override=not _no_override)

    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")
    app.permanent_session_lifetime = timedelta(days=14)
    app.register_blueprint(nav_diagnosis_ai_bp)
    app.register_blueprint(line_seo_bp)

    def _utage_lead_enabled() -> bool:
        return os.environ.get("UTAGE_ENABLED", "").strip() == "1" and bool(
            os.environ.get("UTAGE_API_URL", "").strip()
        )

    def _course_lp_url_external() -> str:
        return url_for("course_lp", _external=True)

    def _premium_url_external() -> str:
        return url_for("premium_ai_report", _external=True)

    def _ai_url_external() -> str:
        return url_for("soul_nav", _external=True)

    def _delay_minutes(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return max(0, int(raw))
        except ValueError:
            return default

    def _ab_free_result_variant() -> str:
        if os.environ.get("AB_FREE_RESULT_ENABLED", "").strip() != "1":
            return "A"
        key = "ab_free_result_variant"
        val = str(session.get(key) or "").strip().upper()
        if val in {"A", "B"}:
            return val
        b_ratio_raw = os.environ.get("AB_FREE_RESULT_B_RATIO", "50").strip()
        try:
            b_ratio = max(0, min(100, int(b_ratio_raw)))
        except ValueError:
            b_ratio = 50
        seed = str(session.get("ab_seed") or "").strip()
        if not seed:
            seed = str(uuid.uuid4())
            session["ab_seed"] = seed
        bucket = sum(ord(c) for c in seed) % 100
        assigned = "B" if bucket < b_ratio else "A"
        session[key] = assigned
        return assigned

    def _append_event(event_name: str, props: Optional[Dict[str, object]] = None) -> None:
        if not event_name:
            return
        root = Path(__file__).resolve().parent / "data"
        root.mkdir(parents=True, exist_ok=True)
        p = root / "events.jsonl"
        payload: Dict[str, object] = {
            "at": utc_now_iso(),
            "event": event_name,
            "endpoint": request.endpoint or "",
            "path": request.path,
            "session_seed": str(session.get("ab_seed") or ""),
        }
        lead_email = str(session.get("lead_email") or "").strip().lower()
        if lead_email:
            payload["lead_email"] = lead_email
        if props:
            payload["props"] = props
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            current_app.logger.exception("append event failed: %s", event_name)

    @app.before_request
    def _process_followup_queue() -> None:
        try:
            process_pending_followups(max_items=2)
        except Exception:
            current_app.logger.exception("followup queue process failed")

    def _result_kwargs_from_session(*, for_email: bool = False) -> Optional[Dict[str, object]]:
        """セッションから結果ページ用のテンプレ変数を組み立てる（MARKETING_COPY はモジュール参照）。

        for_email=True のときはミニ要約（OpenAI）をこのリクエスト内で新規生成しない（メール送信の遅延・失敗を避ける）。
        """
        best_key = session.get("type_quiz_best_key")
        if not isinstance(best_key, str) or best_key not in SOUL_TYPES:
            return None
        raw_scores = session.get("type_quiz_scores_by_key")
        if not isinstance(raw_scores, dict):
            return None
        scores: Dict[str, int] = {}
        for k, v in raw_scores.items():
            if k not in SOUL_TYPES:
                continue
            try:
                scores[k] = int(v)
            except (TypeError, ValueError):
                return None
        if not scores:
            return None
        soul_type = SOUL_TYPES[best_key]
        sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        display_scores = [(SOUL_TYPES[k].name, v) for k, v in sorted_scores]
        consciousness = map_type_scores_to_consciousness(
            scores_by_key=scores,
            top_type_name=soul_type.name,
        )
        marketing = MARKETING_COPY.get(best_key, {})
        _default = {"empathy": "", "problem": "", "cause": "", "solution": "", "future": ""}
        marketing = {**_default, **marketing}
        answers = session.get("type_quiz_answers")
        quiz_answers = answers if isinstance(answers, dict) else {}
        qa_int: Dict[str, int] = {}
        if isinstance(answers, dict):
            for q in QUESTIONS:
                v = answers.get(q.key)
                try:
                    if v is not None:
                        iv = int(v)
                        if iv in {1, 2, 3, 4, 5}:
                            qa_int[q.key] = iv
                except (TypeError, ValueError):
                    pass
        _soul_re, phase_s, navi_s = score_diagnosis(qa_int, QUESTIONS, tuple(SOUL_TYPES.keys()))
        position_profile = build_position_profile(
            phase_scores=phase_s,
            navi_scores=navi_s,
            soul_scores=_soul_re,
            best_key=best_key,
            soul_types=SOUL_TYPES,
            type_priority=SOUL_TYPE_PRIORITY,
        )
        theme_scores = score_themes(qa_int, QUESTIONS)
        manuscript_insight = build_manuscript_insight(
            phase_key=str(position_profile.get("phase_key") or ""),
            best_type_key=best_key,
            theme_scores=theme_scores,
        )
        result_variant = _ab_free_result_variant()
        result_sections = build_type_result(
            best_key=best_key,
            soul_type_name=soul_type.name,
            fallback_summary=soul_type.summary,
        )

        mini_summary_text = ""
        if os.environ.get("FREE_DIAGNOSIS_MINI_SUMMARY", "1").strip() != "0":
            lead_blocks = _utage_lead_enabled() and not bool(session.get("diagnosis_lead_registered"))
            if not for_email and not lead_blocks and _quiz_complete(qa_int):
                if "type_quiz_mini_summary" not in session:
                    if _openai_runtime_ready():
                        try:
                            _challenge = str(session.get("type_quiz_challenge_note") or "").strip()
                            _parts = build_strings_for_mini_summary(
                                answers=qa_int,
                                questions=QUESTIONS,
                                likert_choices=LIKERT_CHOICES,
                                best_key=best_key,
                                soul_types=SOUL_TYPES,
                                soul_type_priority=SOUL_TYPE_PRIORITY,
                                position_profile=position_profile,
                                manuscript_insight=manuscript_insight,
                                soul_scores=scores,
                                challenge_note=_challenge,
                            )
                            try:
                                _mt = int(
                                    (os.environ.get("FREE_DIAGNOSIS_MINI_MAX_TOKENS", "") or "900").strip()
                                    or "900"
                                )
                            except ValueError:
                                _mt = 900
                            session["type_quiz_mini_summary"] = generate_mini_diagnosis_summary(
                                **_parts,
                                max_tokens=_mt,
                            )
                        except Exception:
                            current_app.logger.exception("free mini diagnosis summary failed")
                            session["type_quiz_mini_summary"] = ""
                    else:
                        session["type_quiz_mini_summary"] = ""
                mini_summary_text = str(session.get("type_quiz_mini_summary") or "")
            elif for_email:
                # メール用: 既にセッションにあれば載せる（このリクエストで OpenAI は呼ばない）
                mini_summary_text = str(session.get("type_quiz_mini_summary") or "")

        return {
            "soul_type": soul_type,
            "scores": display_scores,
            "max_score": max(scores.values()) if scores else 0,
            "marketing": marketing,
            "consciousness": consciousness,
            "questions": QUESTIONS,
            "quiz_answers": quiz_answers,
            "lead_registered": bool(session.get("diagnosis_lead_registered")),
            "result_variant": result_variant,
            "result_sections": result_sections,
            "position_profile": position_profile,
            "manuscript_insight": manuscript_insight,
            "mini_summary_text": mini_summary_text,
            "challenge_note_user": str(session.get("type_quiz_challenge_note") or "").strip(),
        }

    def _clear_30_question_state() -> None:
        for key in (
            "type_quiz_answers",
            "type_quiz_best_key",
            "type_quiz_scores_by_key",
            "type_quiz_mini_summary",
            "type_quiz_challenge_note",
            "diagnosis_lead_registered",
            "diagnosis_lead_synced",
            "lead_email",
            "lead_name",
        ):
            session.pop(key, None)

    def _clear_simple_diagnosis_state() -> None:
        for key in (
            "simple_diagnosis_completed",
            "simple_diagnosis_level",
            "simple_diagnosis_answers",
        ):
            session.pop(key, None)

    def _simple_diagnosis_done() -> bool:
        return bool(session.get("simple_diagnosis_completed"))

    def _diagnosis_entry_gate_passed() -> bool:
        return bool(session.get("diagnosis_lead_registered")) and bool(
            str(session.get("lead_email") or "").strip()
        )

    def _render_diagnosis_email_gate() -> str:
        level = str(session.get("simple_diagnosis_level") or "").strip()
        simple_template = SIMPLE_RESULT_TEMPLATES.get(level, SIMPLE_RESULT_TEMPLATES["mid"])
        return render_template(
            "diagnosis_email_gate.html",
            simple_level=level if level in SIMPLE_RESULT_TEMPLATES else "mid",
            simple_template=simple_template,
            saved_email=str(session.get("lead_email") or "").strip(),
            saved_name=str(session.get("lead_name") or "").strip(),
        )

    def _sync_registered_lead_after_result() -> None:
        if not _diagnosis_entry_gate_passed():
            return
        if bool(session.get("diagnosis_lead_synced")):
            return

        best_key = session.get("type_quiz_best_key")
        raw_scores = session.get("type_quiz_scores_by_key")
        email = str(session.get("lead_email") or "").strip()
        name = str(session.get("lead_name") or "").strip()

        if not email:
            return
        if not isinstance(best_key, str) or best_key not in SOUL_TYPES:
            return
        if not isinstance(raw_scores, dict):
            return

        scores_by_key: Dict[str, int] = {}
        for k, v in raw_scores.items():
            if k in SOUL_TYPES:
                try:
                    scores_by_key[k] = int(v)
                except (TypeError, ValueError):
                    pass
        if not scores_by_key:
            return

        st = SOUL_TYPES[best_key]
        sync_ok = True
        detail = "skipped"
        if _utage_lead_enabled():
            src = os.environ.get("UTAGE_SOURCE", "soul_quiz").strip() or "soul_quiz"
            payload = build_utage_payload(
                email=email,
                name=name,
                best_key=best_key,
                type_label=st.name,
                scores_by_key=scores_by_key,
                source=src,
            )
            sync_ok, detail = post_utage_lead(payload)
            append_lead_log(sync_ok, email, detail)
            if sync_ok:
                current_app.logger.info("UTAGE lead ok: %s", detail)
            else:
                current_app.logger.warning("UTAGE lead failed: %s", detail)
                return

        session["diagnosis_lead_synced"] = True
        _append_event("lead_register_synced")
        enqueue_followup(
            email=email,
            name=name,
            kind="result_no_course",
            context={
                "course_url": _course_lp_url_external(),
                "premium_url": _premium_url_external(),
                "ai_url": _ai_url_external(),
                "type_name": st.name,
            },
            delay_minutes=_delay_minutes("FOLLOWUP_RESULT_NO_COURSE_DELAY_MIN", 4 * 60),
            dedupe_key="result_no_course_v1",
        )
        if is_diagnosis_result_email_enabled():
            email_delay_min = _diagnosis_result_email_delay_minutes()
            insight = map_type_scores_to_consciousness(
                scores_by_key=scores_by_key,
                top_type_name=st.name,
            )
            guide_video = _diagnosis_line_funnel_url()
            guide_title = _diagnosis_line_funnel_title()
            rk_email = _result_kwargs_from_session(for_email=True)
            _link_kw = {
                "education_video_page_url": url_for("education_video", _external=True),
                "guide_video_url": guide_video,
                "guide_video_title": guide_title,
                "unsubscribe_url": url_for("unsubscribe", email=email, _external=True),
            }
            full_plain = ""
            if rk_email is not None:
                full_plain = format_diagnosis_result_plain_text(
                    rk_email,
                    recipient_name=name,
                    links=_link_kw,
                )
                current_app.logger.info(
                    "Diagnosis email body: full text, len=%s", len(full_plain)
                )
            else:
                current_app.logger.warning(
                    "Diagnosis email: session result kwargs missing, using minimal body"
                )
                rs_fb = build_type_result(
                    best_key=best_key,
                    soul_type_name=st.name,
                    fallback_summary=st.summary,
                )
                _mdef = {"empathy": "", "problem": "", "cause": "", "solution": "", "future": ""}
                _mkt = {**_mdef, **MARKETING_COPY.get(best_key, {})}
                sorted_s = sorted(scores_by_key.items(), key=lambda kv: kv[1], reverse=True)
                disp = [(SOUL_TYPES[k].name, int(v)) for k, v in sorted_s if k in SOUL_TYPES]
                mx = max(scores_by_key.values()) if scores_by_key else 1
                full_plain = format_diagnosis_result_minimal_fallback(
                    recipient_name=name,
                    type_name=st.name,
                    one_liner=str(rs_fb.get("one_liner") or st.summary),
                    insight=insight,
                    marketing=_mkt,
                    display_scores=disp,
                    max_score=mx if mx > 0 else 1,
                    links=_link_kw,
                )
            email_payload = {
                "type_name": st.name,
                "alignment_state": insight.alignment_state,
                "consciousness_level": insight.consciousness_level,
                "consciousness_label": insight.consciousness_label,
                "consciousness_emotion": insight.consciousness_emotion,
                "energy_score": insight.energy_score,
                "body_signal_summary": insight.body_signal_summary,
                "misalignment_reason": insight.misalignment_reason,
                "future_if_aligned": insight.future_if_aligned,
                "next_action": insight.next_action,
                "guide_video_url": guide_video,
                "guide_video_title": guide_title,
                "full_result_plaintext": full_plain,
            }
            if _is_email_unsubscribed(email):
                current_app.logger.info("Diagnosis result email skipped (unsubscribed): %s", email)
            else:
                queued = enqueue_followup(
                    email=email,
                    name=name,
                    kind="diagnosis_result_email",
                    context=email_payload,
                    delay_minutes=email_delay_min,
                    dedupe_key=f"diagnosis_result_email_{uuid.uuid4().hex}",
                )
                if queued:
                    current_app.logger.info("Diagnosis result email queued for %s", email)
                else:
                    current_app.logger.warning("Diagnosis result email queue skipped for %s", email)
        else:
            current_app.logger.info(
                "Diagnosis result email skipped (set DIAG_RESULT_EMAIL_ENABLED=1 to enable)"
            )

    def _render_diagnosis_top(
        *,
        errors: Optional[List[str]] = None,
        previous_answers: Optional[Dict[str, int]] = None,
        previous_challenge_note: str = "",
        status_code: int = 200,
    ) -> Tuple[str, int] | str:
        rendered = render_template(
            "diagnosis.html",
            questions=QUESTIONS,
            likert_choices=LIKERT_CHOICES,
            errors=errors,
            previous_answers=previous_answers,
            previous_challenge_note=previous_challenge_note,
            challenge_note_max_len=CHALLENGE_NOTE_MAX_LEN,
            diagnosis_challenge_field=DIAGNOSIS_CHALLENGE_FIELD,
        )
        if status_code == 200:
            return rendered
        return rendered, status_code

    @app.context_processor
    def inject_product_pricing() -> Dict[str, object]:
        course_url = os.environ.get("SOUL_COURSE_PURCHASE_URL", "").strip() or _DEFAULT_SOUL_COURSE_NORMAL_URL
        course_cta = os.environ.get("SOUL_COURSE_CTA_LABEL", "").strip() or "魂のナビ講座を見る"

        # GA4 / Search Console: ドメイン別に環境変数から取得
        _h = _request_hostname()
        if _h in ("life-energy-coaching.net", "www.life-energy-coaching.net"):
            _ga_id = os.environ.get("GA_MEASUREMENT_ID_LEC", "").strip()
            _sc_verification = os.environ.get("SEARCH_CONSOLE_META_LEC", "").strip()
        elif _h in ("gaiaarts.org", "www.gaiaarts.org"):
            _ga_id = os.environ.get("GA_MEASUREMENT_ID_GAIA", "").strip()
            _sc_verification = os.environ.get("SEARCH_CONSOLE_META_GAIA", "").strip()
        else:
            _ga_id = os.environ.get("GA_MEASUREMENT_ID", "").strip()
            _sc_verification = os.environ.get("SEARCH_CONSOLE_META", "").strip()

        return {
            "seo_canonical_url": _seo_canonical_url(),
            "nav_handoff_payment_live": os.environ.get("NAV_HANDOFF_PAYMENT_LIVE", "").strip() == "1",
            "soul_course_purchase_url": course_url,
            "soul_course_cta_label": course_cta,
            "soul_course_price": os.environ.get("SOUL_COURSE_PRICE", "").strip() or "98,000円（税込）",
            "soul_course_format": os.environ.get("SOUL_COURSE_FORMAT", "").strip() or "オンライン（Zoom）",
            "soul_course_sessions": os.environ.get("SOUL_COURSE_SESSIONS", "").strip() or "全5回",
            "soul_course_period": os.environ.get("SOUL_COURSE_PERIOD", "").strip() or "90日",
            "soul_course_support": os.environ.get("SOUL_COURSE_SUPPORT", "").strip(),
            "soul_course_capacity": os.environ.get("SOUL_COURSE_CAPACITY", "").strip() or "各期12名",
            "soul_course_bonus": os.environ.get("SOUL_COURSE_BONUS", "").strip()
            or "Zoom個人セッション（60分）2回",
            "soul_course_after_apply": os.environ.get("SOUL_COURSE_AFTER_APPLY", "").strip()
            or "申込完了メール → 個人セッション日程案内 → 初回講座参加",
            "education_video_title": _education_video_title(),
            "education_video_url": _education_video_url(),
            "education_video_embed_url": _education_video_embed_url(),
            "closing_course_video_title": _closing_course_video_title(),
            "closing_course_video_url": _closing_course_video_url(),
            "closing_course_video_embed_url": _closing_course_video_embed_url(),
            "line_register_url": _line_register_url(),
            "diagnosis_line_funnel_url": _diagnosis_line_funnel_url(),
            "privacy_policy_url": _privacy_policy_url(),
            "tokusho_url": _tokusho_url(),
            "company_url": _company_url(),
            "soul_course_early_url": os.environ.get("SOUL_COURSE_EARLY_URL", "").strip()
            or _DEFAULT_SOUL_COURSE_EARLY_URL,
            "soul_course_normal_url": course_url,
            "soul_course_thanks_url": os.environ.get("SOUL_COURSE_THANKS_URL", "").strip()
            or _DEFAULT_SOUL_COURSE_THANKS_URL,
            # テンプレ・解放判定用（キー + openai パッケージ。未整備のまま有料相当の解放をさせない）
            "openai_configured": _openai_runtime_ready(),
            "soul_nav_min_user_chars": _soul_nav_min_user_chars(),
            "utage_lead_enabled": _utage_lead_enabled(),
            "premium_bundle_name": os.environ.get("PREMIUM_BUNDLE_NAME", "").strip() or "深掘りパック",
            "premium_bundle_tagline": os.environ.get("PREMIUM_BUNDLE_TAGLINE", "").strip()
            or "本格レポート ＋ 魂のナビAI",
            "premium_bundle_price_label": os.environ.get("PREMIUM_BUNDLE_PRICE_LABEL", "").strip()
            or "5,000円（税込）",
            # SEO: GA4 / Search Console（ドメイン別・未設定時は空文字）
            "ga_measurement_id": _ga_id,
            "search_console_verification": _sc_verification,
        }

    @app.get("/")
    def site_root():
        """ドメインで振り分け: Gaia=英語トップ、ライフエネルギー=LEC、その他は診断LP（/navi）へ。"""
        if _is_gaia_public_host():
            return render_template("en_landing.html")
        if _is_life_energy_public_host():
            return render_template("lec_landing.html")
        return redirect(url_for("landing"), code=308)

    @app.get("/navi")
    def landing():
        """無料診断LP（日本語・魂のナビ）。tamashiinavi 等は / → /navi に誘導。"""
        return render_template("landing.html")

    @app.get("/navi/")
    def landing_slash():
        return redirect(url_for("landing"), code=308)

    @app.get("/en")
    def en_landing():
        if _is_gaia_public_host():
            return redirect(url_for("site_root"), code=308)
        return render_template("en_landing.html")

    @app.get("/lec", strict_slashes=False)
    def lec_landing():
        """ライフエネルギーコーチング名古屋（多言語ランディング・独自デザイン）。

        nginx が /lec → /lec/ と 301 する構成と衝突しないよう、末尾スラッシュ有無の両方で同一レスポンスにする。
        """
        return render_template("lec_landing.html")

    @app.get("/en/lec")
    def lec_landing_en_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_landing_en"), code=308)

    @app.get("/en/lec/")
    def lec_landing_en():
        """英語LP（検索・hreflang 用）。canonical は /en/lec/。本文は既存 i18n + 先頭で lang=en を適用。"""
        _require_life_energy_seo_host()
        return render_template(
            "lec_landing.html",
            lec_lp_locale="en",
            seo_canonical_url=_lec_public_en_canonical("/en/lec/"),
        )

    @app.get("/lec/en")
    def lec_landing_en_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_landing_en_lec"), code=308)

    @app.get("/lec/en/")
    def lec_landing_en_lec():
        """Nginx が /en/ を渡さないときの英語LPミラー。canonical は /en/lec/ に統一。"""
        _require_life_energy_seo_host()
        return render_template(
            "lec_landing.html",
            lec_lp_locale="en",
            seo_canonical_url=_lec_public_en_canonical("/en/lec/"),
        )

    @app.post("/lec/contact")
    def lec_contact_submit():
        name = str(request.form.get("name") or "").strip()
        email = str(request.form.get("email") or "").strip().lower()
        phone = str(request.form.get("phone") or "").strip()
        preferred_lang = str(request.form.get("preferred_lang") or "").strip()
        video_url = str(request.form.get("video_url") or "").strip()
        message = str(request.form.get("message") or "").strip()
        website = str(request.form.get("website") or "").strip()  # honeypot

        if website:
            flash("送信に失敗しました。時間をおいて再度お試しください。", "error")
            return redirect(url_for("lec_landing") + "#contact")

        _client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        if _client_ip in _lec_blocked_ips():
            flash("送信に失敗しました。時間をおいて再度お試しください。", "error")
            return redirect(url_for("lec_landing") + "#contact")
        if name.lower() in _lec_blocked_names():
            flash("送信に失敗しました。時間をおいて再度お試しください。", "error")
            return redirect(url_for("lec_landing") + "#contact")
        if _lec_rate_limited(_client_ip):
            flash("送信が多すぎます。しばらく時間をおいてからお試しください。", "error")
            return redirect(url_for("lec_landing") + "#contact")

        if not name or not email or not message:
            flash("お名前・メールアドレス・お問い合わせ内容は必須です。", "error")
            return redirect(url_for("lec_landing") + "#contact")
        if "@" not in email or "." not in email.split("@")[-1]:
            flash("メールアドレスの形式をご確認ください。", "error")
            return redirect(url_for("lec_landing") + "#contact")

        payload = {
            "created_at": utc_now_iso(),
            "path": request.path,
            "name": name,
            "email": email,
            "phone": phone,
            "preferred_lang": preferred_lang,
            "video_url": video_url,
            "message": message,
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
            "user_agent": request.headers.get("User-Agent", ""),
        }
        try:
            with _lec_inquiries_file().open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            current_app.logger.exception("lec inquiry save failed")
            flash("送信に失敗しました。時間をおいて再度お試しください。", "error")
            return redirect(url_for("lec_landing") + "#contact")

        _append_event("lec_contact_submit", {"preferred_lang": preferred_lang, "has_video_url": bool(video_url)})

        # スパム判定：スコアが高い場合はクォランティンに保存してメール通知しない
        _spam_score = _lec_spam_score(name, email, phone, message, _client_ip)
        if _spam_score >= 60:
            _lec_quarantine(payload, _spam_score)
        else:
            _send_lec_notify_email(name, email, phone, preferred_lang, message)

        flash("お問い合わせを受け付けました。通常24時間以内にご返信します。", "success")
        return redirect(url_for("lec_landing") + "#contact")

    @app.get("/sitemap.xml")
    def sitemap_xml():
        """ドメイン別 sitemap.xml を返す。未対応ドメインは 404。"""
        h = _request_hostname()
        if h in ("gaiaarts.org", "www.gaiaarts.org"):
            domain = "gaiaarts.org"
            urls = [
                ("https://gaiaarts.org/", "1.0", "monthly"),
                ("https://gaiaarts.org/services/hospitality-training/", "0.9", "monthly"),
                ("https://gaiaarts.org/services/leadership-development/", "0.9", "monthly"),
                ("https://gaiaarts.org/regions/cambodia/", "0.85", "monthly"),
                ("https://gaiaarts.org/regions/philippines/", "0.85", "monthly"),
                ("https://gaiaarts.org/regions/indonesia/", "0.85", "monthly"),
                ("https://gaiaarts.org/regions/mongolia/", "0.85", "monthly"),
                ("https://gaiaarts.org/japanese-product-sourcing/", "0.85", "monthly"),
                ("https://gaiaarts.org/about/kenji-katagiri/", "0.85", "monthly"),
                ("https://gaiaarts.org/hair/", "0.88", "monthly"),
                ("https://gaiaarts.org/insights/", "0.8", "weekly"),
            ]
            urls.extend(
                (
                    f"https://gaiaarts.org/insights/{a['slug']}/",
                    "0.72",
                    "monthly",
                )
                for a in GAIA_INSIGHT_ARTICLES
            )
            urls.append(("https://gaiaarts.org/jp/insights/", "0.78", "weekly"))
            urls.extend(
                (
                    f"https://gaiaarts.org/jp/insights/{a['slug']}/",
                    "0.7",
                    "monthly",
                )
                for a in gaia_jp_insights_sorted()
            )
        elif h in ("life-energy-coaching.net", "www.life-energy-coaching.net"):
            domain = "life-energy-coaching.net"
            urls = [
                ("https://life-energy-coaching.net/", "1.0", "monthly"),
                ("https://life-energy-coaching.net/lec/", "1.0", "monthly"),
                ("https://life-energy-coaching.net/en/lec/", "0.95", "weekly"),
                ("https://life-energy-coaching.net/lec/en/", "0.94", "weekly"),
                ("https://life-energy-coaching.net/kinesiology/", "0.9", "monthly"),
                ("https://life-energy-coaching.net/chakra-healing/", "0.9", "monthly"),
                ("https://life-energy-coaching.net/en/kinesiology/", "0.85", "monthly"),
                ("https://life-energy-coaching.net/en/chakra-healing/", "0.85", "monthly"),
                ("https://life-energy-coaching.net/lec/en/kinesiology/", "0.84", "monthly"),
                ("https://life-energy-coaching.net/lec/en/chakra-healing/", "0.84", "monthly"),
                ("https://life-energy-coaching.net/en/blog/", "0.82", "weekly"),
                ("https://life-energy-coaching.net/lec/en/blog/", "0.82", "weekly"),
                ("https://life-energy-coaching.net/blog/", "0.85", "weekly"),
                ("https://life-energy-coaching.net/lec/kinesiology/", "0.88", "monthly"),
                ("https://life-energy-coaching.net/lec/chakra-healing/", "0.88", "monthly"),
                ("https://life-energy-coaching.net/lec/blog/", "0.86", "weekly"),
            ]
            urls.extend(
                (
                    f"https://life-energy-coaching.net/blog/{e['slug']}/",
                    "0.75",
                    "monthly",
                )
                for e in LEC_COLUMN_ENTRIES
                if e.get("status") == "live"
                and e.get("slug") not in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS
            )
            urls.extend(
                (
                    f"https://life-energy-coaching.net/en/blog/{e['slug']}/",
                    "0.72",
                    "monthly",
                )
                for e in LEC_COLUMN_ENTRIES
                if lec_column_has_english(e)
                and e.get("slug") not in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS
            )
        else:
            return "", 404

        today = date.today().isoformat()
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for loc, priority, changefreq in urls:
            lines.append(
                f"  <url>"
                f"<loc>{loc}</loc>"
                f"<lastmod>{today}</lastmod>"
                f"<changefreq>{changefreq}</changefreq>"
                f"<priority>{priority}</priority>"
                f"</url>"
            )
        lines.append("</urlset>")
        content = "\n".join(lines) + "\n"
        return Response(content, status=200, mimetype="application/xml")

    @app.get("/robots.txt")
    def robots_txt():
        """ドメイン別 robots.txt を返す。"""
        h = _request_hostname()
        if h in ("gaiaarts.org", "www.gaiaarts.org"):
            domain = "gaiaarts.org"
        elif h in ("life-energy-coaching.net", "www.life-energy-coaching.net"):
            domain = "life-energy-coaching.net"
        else:
            domain = h
        content = (
            "User-agent: *\n"
            "Allow: /\n"
            "\n"
            "# AI crawlers — explicitly allowed\n"
            "User-agent: GPTBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: Google-Extended\n"
            "Allow: /\n"
            "\n"
            "User-agent: PerplexityBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: ClaudeBot\n"
            "Allow: /\n"
            "\n"
            "User-agent: Applebot-Extended\n"
            "Allow: /\n"
            "\n"
            "User-agent: cohere-ai\n"
            "Allow: /\n"
            "\n"
            "User-agent: Amazonbot\n"
            "Allow: /\n"
            "\n"
            f"Sitemap: https://{domain}/sitemap.xml\n"
        )
        return Response(content, status=200, mimetype="text/plain")

    @app.get("/llms.txt")
    def llms_txt():
        """LLM向けサイト概要ファイル（llmstxt.org 仕様）。ドメイン別に返す。"""
        h = _request_hostname()
        if h in ("gaiaarts.org", "www.gaiaarts.org"):
            content = """\
# Gaia Arts

> Gaia Arts is a Japan-based consulting firm specializing in hospitality training and leadership development across Southeast Asia. Founded by Kenji Katagiri, the firm partners with hotels, restaurants, tourism businesses, and Japanese companies expanding into Asia.

Gaia Arts delivers on-site training programs and organizational consulting in Cambodia, Philippines, Indonesia, and Mongolia. The approach blends Japanese service culture (omotenashi) with local context to build high-performing, guest-centric teams.

## Services

- [Hospitality Training](https://gaiaarts.org/services/hospitality-training/): Professional service excellence programs for hotels, restaurants, and tourism businesses in Southeast Asia. Covers guest communication, team leadership, and Japanese-standard service delivery.
- [Leadership Development](https://gaiaarts.org/services/leadership-development/): Executive coaching and organizational development for Japanese companies and international teams operating in Asia.
- [Japanese Product Sourcing](https://gaiaarts.org/japanese-product-sourcing/): Supporting Southeast Asian businesses in sourcing quality Japanese products and building supplier relationships.

## Founder

- [Kenji Katagiri](https://gaiaarts.org/about/kenji-katagiri/): Founder and chief consultant. Cross-cultural trainer with deep experience in Southeast Asian hospitality markets and Japanese organizational culture.

## Nagoya hair salon

- [GaiaArtsHair](https://gaiaarts.org/hair/) (Japanese): Hair salon in Nagoya (Shin-Sakae). Booking and inquiries via the Life Energy Coaching contact form.

## Regional Expertise

- [Cambodia](https://gaiaarts.org/regions/cambodia/)
- [Philippines](https://gaiaarts.org/regions/philippines/)
- [Indonesia](https://gaiaarts.org/regions/indonesia/)
- [Mongolia](https://gaiaarts.org/regions/mongolia/)

## Insights & Articles

- [Business Insights (English)](https://gaiaarts.org/insights/): Research and perspectives on Southeast Asian hospitality, leadership, and cross-cultural business.
- [ビジネスインサイト（日本語）](https://gaiaarts.org/jp/insights/): 東南アジアのホスピタリティ・リーダーシップに関する日本語記事。

## Contact

Schedule a meeting: https://gaiaarts.org/#contact
"""
        elif _is_life_energy_public_host():
            content = """\
# Life Energy Coaching（ライフエネルギーコーチング）

> ライフエネルギーコーチングは、名古屋を拠点とするホリスティックコーチング・エネルギーヒーリングのサービスです。キネシオロジー（筋肉テスト）とチャクラヒーリングを通じて、潜在意識のブロックを解放し、魂の使命と現実をつなぐサポートをしています。

創設者の片桐健治（Kenji Katagiri）は、東洋の叡智と実践的なコーチング手法を統合し、クライアントが自分のエネルギーを整え、人生の方向性を明確にできるようサポートしています。日本語・英語でのセッションに対応しています。

## サービス / Services

- [キネシオロジーコーチング](https://life-energy-coaching.net/kinesiology/): 筋肉テストを用いて潜在意識のブロックを特定し、エネルギーを整えます。
- [チャクラヒーリング](https://life-energy-coaching.net/chakra-healing/): 7つのチャクラ（エネルギーセンター）を診断・調整し、心身のバランスを回復します。
- [Kinesiology Coaching (English)](https://life-energy-coaching.net/en/kinesiology/): Muscle testing and energy balancing to uncover subconscious blocks and align intentions.
- [Chakra Healing (English)](https://life-energy-coaching.net/en/chakra-healing/): Comprehensive energy center assessment and healing to restore balance across all areas of life.

## コラム・ブログ / Blog

- [心のコラム（日本語）](https://life-energy-coaching.net/blog/): キネシオロジー・チャクラ・エネルギーに関する記事
- [Soul Navigation Blog (English)](https://life-energy-coaching.net/en/blog/): Articles on kinesiology, chakra healing, and holistic coaching.

## Contact / お問い合わせ

Booking and inquiries: https://life-energy-coaching.net/lec/#contact
"""
        else:
            return "", 404

        return Response(content, status=200, mimetype="text/plain; charset=utf-8")

    def _require_life_energy_seo_host() -> None:
        if not _is_life_energy_public_host():
            abort(404)

    def _require_gaia_seo_host() -> None:
        if not _is_gaia_public_host():
            abort(404)

    # --- life-energy-coaching.net 専用サブページ（Nginx で同パスを Flask に転送すること）---
    @app.get("/kinesiology")
    def lec_kinesiology_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_kinesiology"), code=308)

    @app.get("/kinesiology/")
    def lec_page_kinesiology():
        _require_life_energy_seo_host()
        return render_template("lec_kinesiology.html")

    @app.get("/chakra-healing")
    def lec_chakra_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_chakra_healing"), code=308)

    @app.get("/chakra-healing/")
    def lec_page_chakra_healing():
        _require_life_energy_seo_host()
        return render_template("lec_chakra_healing.html")

    @app.get("/lec/kinesiology")
    def lec_kinesiology_jp_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_kinesiology_lec"), code=308)

    @app.get("/lec/kinesiology/")
    def lec_page_kinesiology_lec():
        """Nginx が /kinesiology を静的配信する構成用。canonical は /kinesiology/。"""
        _require_life_energy_seo_host()
        return render_template(
            "lec_kinesiology.html",
            seo_canonical_url=_lec_public_jp_canonical("/kinesiology/"),
        )

    @app.get("/lec/chakra-healing")
    def lec_chakra_jp_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_chakra_healing_lec"), code=308)

    @app.get("/lec/chakra-healing/")
    def lec_page_chakra_healing_lec():
        _require_life_energy_seo_host()
        return render_template(
            "lec_chakra_healing.html",
            seo_canonical_url=_lec_public_jp_canonical("/chakra-healing/"),
        )

    @app.get("/en/kinesiology")
    def lec_kinesiology_en_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_kinesiology_en_lec"), code=308)

    @app.get("/en/kinesiology/")
    def lec_page_kinesiology_en():
        _require_life_energy_seo_host()
        return render_template("lec_kinesiology_en.html")

    @app.get("/lec/en/kinesiology")
    def lec_kinesiology_en_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_kinesiology_en_lec"), code=308)

    @app.get("/lec/en/kinesiology/")
    def lec_page_kinesiology_en_lec():
        """Nginx が /en/ を Flask に渡さない構成でも /lec/ 経由で英語ページを出す。"""
        _require_life_energy_seo_host()
        return render_template(
            "lec_kinesiology_en.html",
            seo_canonical_url=_lec_public_en_canonical("/en/kinesiology/"),
        )

    @app.get("/en/chakra-healing")
    def lec_chakra_healing_en_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_chakra_healing_en_lec"), code=308)

    @app.get("/en/chakra-healing/")
    def lec_page_chakra_healing_en():
        _require_life_energy_seo_host()
        return render_template("lec_chakra_healing_en.html")

    @app.get("/lec/en/chakra-healing")
    def lec_chakra_healing_en_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_chakra_healing_en_lec"), code=308)

    @app.get("/lec/en/chakra-healing/")
    def lec_page_chakra_healing_en_lec():
        _require_life_energy_seo_host()
        return render_template(
            "lec_chakra_healing_en.html",
            seo_canonical_url=_lec_public_en_canonical("/en/chakra-healing/"),
        )

    @app.get("/blog")
    def lec_blog_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_blog"), code=308)

    @app.get("/blog/")
    def lec_page_blog():
        _require_life_energy_seo_host()
        return render_template("lec_blog.html", column_entries=LEC_COLUMN_ENTRIES)

    @app.get("/lec/blog")
    def lec_blog_jp_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_blog_lec"), code=308)

    @app.get("/lec/blog/")
    def lec_page_blog_lec():
        _require_life_energy_seo_host()
        return render_template(
            "lec_blog.html",
            column_entries=LEC_COLUMN_ENTRIES,
            seo_canonical_url=_lec_public_jp_canonical("/blog/"),
        )

    @app.get("/en/blog")
    def lec_blog_en_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_blog_en_lec"), code=308)

    @app.get("/en/blog/")
    def lec_page_blog_en():
        _require_life_energy_seo_host()
        return render_template(
            "lec_blog_en.html",
            column_entries=lec_column_entries_english_live(),
        )

    @app.get("/lec/en/blog")
    def lec_blog_en_lec_no_slash():
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_blog_en_lec"), code=308)

    @app.get("/lec/en/blog/")
    def lec_page_blog_en_lec():
        _require_life_energy_seo_host()
        return render_template(
            "lec_blog_en.html",
            column_entries=lec_column_entries_english_live(),
            seo_canonical_url=_lec_public_en_canonical("/en/blog/"),
        )

    @app.get("/blog/<slug>")
    def lec_column_post_no_slash(slug: str):
        _require_life_energy_seo_host()
        return redirect(url_for("lec_column_post", slug=slug), code=308)

    @app.get("/blog/<slug>/")
    def lec_column_post(slug: str):
        _require_life_energy_seo_host()
        if slug in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS:
            return redirect(f"https://gaiaarts.org/jp/insights/{slug}/", code=308)
        entry = _lec_column_by_slug(slug)
        if not entry or entry.get("status") != "live":
            abort(404)
        return render_template("lec_column_article.html", entry=entry)

    @app.get("/lec/blog/<slug>")
    def lec_column_post_lec_no_slash(slug: str):
        _require_life_energy_seo_host()
        return redirect(url_for("lec_column_post_lec", slug=slug), code=308)

    @app.get("/lec/blog/<slug>/")
    def lec_column_post_lec(slug: str):
        _require_life_energy_seo_host()
        if slug in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS:
            return redirect(f"https://gaiaarts.org/jp/insights/{slug}/", code=308)
        entry = _lec_column_by_slug(slug)
        if not entry or entry.get("status") != "live":
            abort(404)
        return render_template(
            "lec_column_article.html",
            entry=entry,
            seo_canonical_url=_lec_public_jp_canonical(f"/blog/{slug}/"),
        )

    @app.get("/en/blog/<slug>")
    def lec_column_post_en_no_slash(slug: str):
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_column_en_lec", slug=slug), code=308)

    @app.get("/en/blog/<slug>/")
    def lec_column_post_en(slug: str):
        _require_life_energy_seo_host()
        if slug in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS:
            return redirect(f"https://gaiaarts.org/jp/insights/{slug}/", code=308)
        entry = _lec_column_by_slug(slug)
        if not lec_column_has_english(entry):
            abort(404)
        return render_template("lec_column_article_en.html", entry=entry)

    @app.get("/lec/en/blog/<slug>")
    def lec_column_post_en_lec_no_slash(slug: str):
        _require_life_energy_seo_host()
        return redirect(url_for("lec_page_column_en_lec", slug=slug), code=308)

    @app.get("/lec/en/blog/<slug>/")
    def lec_page_column_en_lec(slug: str):
        _require_life_energy_seo_host()
        if slug in GAIA_JP_LEC_BLOG_REDIRECT_SLUGS:
            return redirect(f"https://gaiaarts.org/jp/insights/{slug}/", code=308)
        entry = _lec_column_by_slug(slug)
        if not lec_column_has_english(entry):
            abort(404)
        return render_template(
            "lec_column_article_en.html",
            entry=entry,
            seo_canonical_url=_lec_public_en_canonical(f"/en/blog/{slug}/"),
        )

    # --- gaiaarts.org 専用サブページ（location / で届く）---
    @app.get("/services/hospitality-training")
    def gaia_hospitality_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_services_hospitality"), code=308)

    @app.get("/services/hospitality-training/")
    def gaia_services_hospitality():
        _require_gaia_seo_host()
        return render_template("gaia_services_hospitality.html")

    @app.get("/services/leadership-development")
    def gaia_leadership_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_services_leadership"), code=308)

    @app.get("/services/leadership-development/")
    def gaia_services_leadership():
        _require_gaia_seo_host()
        return render_template("gaia_services_leadership.html")

    @app.get("/regions/cambodia")
    def gaia_kh_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_region_cambodia"), code=308)

    @app.get("/regions/cambodia/")
    def gaia_region_cambodia():
        _require_gaia_seo_host()
        return render_template("gaia_region_cambodia.html")

    @app.get("/regions/philippines")
    def gaia_ph_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_region_philippines"), code=308)

    @app.get("/regions/philippines/")
    def gaia_region_philippines():
        _require_gaia_seo_host()
        return render_template("gaia_region_philippines.html")

    @app.get("/regions/indonesia")
    def gaia_id_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_region_indonesia"), code=308)

    @app.get("/regions/indonesia/")
    def gaia_region_indonesia():
        _require_gaia_seo_host()
        return render_template("gaia_region_indonesia.html")

    @app.get("/regions/mongolia")
    def gaia_mn_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_region_mongolia"), code=308)

    @app.get("/regions/mongolia/")
    def gaia_region_mongolia():
        _require_gaia_seo_host()
        return render_template("gaia_region_mongolia.html")

    @app.get("/japanese-product-sourcing")
    def gaia_sourcing_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_japanese_product_sourcing"), code=308)

    @app.get("/japanese-product-sourcing/")
    def gaia_japanese_product_sourcing():
        _require_gaia_seo_host()
        return render_template("gaia_japanese_product_sourcing.html")

    @app.get("/about/kenji-katagiri")
    def gaia_kenji_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_about_kenji"), code=308)

    @app.get("/about/kenji-katagiri/")
    def gaia_about_kenji():
        _require_gaia_seo_host()
        return render_template("gaia_about_kenji.html")

    @app.get("/hair")
    def gaia_hair_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_hair_salon"), code=308)

    @app.get("/hair/")
    def gaia_hair_salon():
        _require_gaia_seo_host()
        hair_files = _hair_salon_static_filenames_sorted()
        hair_hero, hair_gallery = _hair_salon_hero_and_gallery(hair_files)
        hair_image_abs_urls = [
            url_for("static", filename=f"hair/{n}", _external=True) for n in hair_files
        ]
        hair_salon_json_ld = _hair_salon_json_ld(
            canonical_url=_seo_canonical_url(),
            image_abs_urls=hair_image_abs_urls,
        )
        return render_template(
            "gaia_hair_salon.html",
            hair_hero=hair_hero,
            hair_gallery=hair_gallery,
            hair_image_abs_urls=hair_image_abs_urls,
            hair_salon_json_ld=hair_salon_json_ld,
        )

    @app.get("/insights")
    def gaia_insights_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_insights"), code=308)

    @app.get("/insights/")
    def gaia_insights():
        _require_gaia_seo_host()
        return render_template(
            "gaia_insights.html",
            insight_articles=gaia_insights_sorted(),
            insight_planned=gaia_insights_planned(),
        )

    @app.get("/insights/<slug>")
    def gaia_insight_article_no_slash(slug: str):
        _require_gaia_seo_host()
        return redirect(url_for("gaia_insight_article", slug=slug), code=308)

    @app.get("/insights/<slug>/")
    def gaia_insight_article(slug: str):
        _require_gaia_seo_host()
        article = gaia_insight_by_slug(slug)
        if not article:
            abort(404)
        return render_template("gaia_insight_article.html", article=article)

    @app.get("/jp/insights")
    def gaia_jp_insights_no_slash():
        _require_gaia_seo_host()
        return redirect(url_for("gaia_jp_insights"), code=308)

    @app.get("/jp/insights/")
    def gaia_jp_insights():
        _require_gaia_seo_host()
        return render_template(
            "gaia_jp_insights.html",
            jp_insight_articles=gaia_jp_insights_sorted(),
        )

    @app.get("/jp/insights/<slug>")
    def gaia_jp_insight_article_no_slash(slug: str):
        _require_gaia_seo_host()
        return redirect(url_for("gaia_jp_insight_article", slug=slug), code=308)

    @app.get("/jp/insights/<slug>/")
    def gaia_jp_insight_article(slug: str):
        _require_gaia_seo_host()
        article = gaia_jp_insight_by_slug(slug)
        if not article:
            abort(404)
        return render_template("gaia_jp_insight_article.html", article=article)

    @app.get("/course")
    def course_lp():
        lead_email = str(session.get("lead_email") or "").strip().lower()
        if lead_email:
            mark_state(lead_email, "course_lp_viewed", True)
            enqueue_followup(
                email=lead_email,
                name=str(session.get("lead_name") or ""),
                kind="course_no_apply",
                context={
                    "course_url": _course_lp_url_external(),
                    "premium_url": _premium_url_external(),
                    "ai_url": _ai_url_external(),
                    "type_name": str(session.get("type_quiz_best_key") or ""),
                },
                delay_minutes=_delay_minutes("FOLLOWUP_COURSE_NO_APPLY_DELAY_MIN", 24 * 60),
                dedupe_key="course_no_apply_v1",
            )
        _append_event("course_lp_view")
        return render_template("index.html")

    @app.get("/simple-diagnosis")
    def simple_diagnosis():
        return render_template("simple_diagnosis.html")

    @app.post("/simple-result")
    def simple_result():
        answers: List[int] = []
        for i in range(1, 9):
            raw = (request.form.get(f"q{i}") or "").strip()
            try:
                v = int(raw)
            except ValueError:
                v = 0
            if v not in (1, 2, 3, 4, 5):
                flash("すべての設問に回答してください。", "error")
                return redirect(url_for("simple_diagnosis"))
            answers.append(v)
        total = sum(answers)

        if total <= 20:
            level = "low"
        elif total <= 32:
            level = "mid"
        else:
            level = "high"

        session.permanent = True
        _clear_30_question_state()
        session["simple_diagnosis_completed"] = True
        session["simple_diagnosis_level"] = level
        session["simple_diagnosis_answers"] = answers
        _append_event("simple_diagnosis_complete", {"level": level})
        tpl = SIMPLE_RESULT_TEMPLATES[level]

        return render_template(
            "simple_result.html",
            level=level,
            template=tpl,
        )

    @app.get("/diagnosis/email")
    def diagnosis_email_gate():
        if not _simple_diagnosis_done():
            flash("まず8問の簡易診断から進んでください。", "error")
            return redirect(url_for("simple_diagnosis"))
        if _diagnosis_entry_gate_passed():
            return redirect(url_for("index"))
        return _render_diagnosis_email_gate()

    @app.post("/diagnosis/email")
    def diagnosis_email_gate_submit():
        if not _simple_diagnosis_done():
            flash("まず8問の簡易診断から進んでください。", "error")
            return redirect(url_for("simple_diagnosis"))

        email = (request.form.get("email") or "").strip()
        name = (request.form.get("name") or "").strip()
        err = validate_lead_form(email, name)
        if err:
            flash(err, "error")
            return redirect(url_for("diagnosis_email_gate"))

        session.permanent = True
        session["diagnosis_lead_registered"] = True
        session["diagnosis_lead_synced"] = False
        session["lead_email"] = email
        session["lead_name"] = name
        try:
            import datetime as _dt
            _lp = Path(__file__).resolve().parent / "data" / "leads.jsonl"
            _lp.parent.mkdir(parents=True, exist_ok=True)
            _entry = json.dumps({
                "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "email": email,
                "name": name,
                "simple_level": str(session.get("simple_result_level") or ""),
                "source": "email_gate",
            }, ensure_ascii=False)
            _lp.open("a", encoding="utf-8").write(_entry + chr(10))
        except Exception:
            current_app.logger.exception("leads.jsonl write failed")
        _append_event("lead_register_complete", {"stage": "before_diagnosis"})
        return redirect(url_for("index"))

    @app.get("/diagnosis")
    def index():
        if not _simple_diagnosis_done():
            flash("まず8問の簡易診断から現在地を確認してください。", "error")
            return redirect(url_for("simple_diagnosis"))
        if not _diagnosis_entry_gate_passed():
            flash("30問の本診断に進む前に、結果の受け取り先を設定してください。", "error")
            return redirect(url_for("diagnosis_email_gate"))
        return _render_diagnosis_top()

    @app.post("/result")
    def result():
        if not _simple_diagnosis_done():
            flash("まず8問の簡易診断から進んでください。", "error")
            return redirect(url_for("simple_diagnosis"))
        if not _diagnosis_entry_gate_passed():
            flash("30問の結果を受け取る前に、メール設定を完了してください。", "error")
            return redirect(url_for("diagnosis_email_gate"))
        answers: Dict[str, int] = {}
        errors: List[str] = []

        challenge_note = (request.form.get(DIAGNOSIS_CHALLENGE_FIELD) or "").strip()
        if len(challenge_note) > CHALLENGE_NOTE_MAX_LEN:
            errors.append(
                f"「いまの課題・気になっていること」は{CHALLENGE_NOTE_MAX_LEN}文字以内にしてください。"
            )

        for q in QUESTIONS:
            raw = request.form.get(q.key, "").strip()
            if not raw:
                errors.append(f"未回答の質問があります（{q.text}）")
                continue
            try:
                val = int(raw)
            except ValueError:
                errors.append(f"回答形式が不正です（{q.text}）")
                continue
            if val not in {1, 2, 3, 4, 5}:
                errors.append(f"回答範囲が不正です（{q.text}）")
                continue
            answers[q.key] = val

        if errors:
            return _render_diagnosis_top(
                errors=errors,
                previous_answers=answers,
                previous_challenge_note=challenge_note,
                status_code=400,
            )

        scores = score_answers(answers)
        best_key = pick_type(scores)

        # 回答・課題メモが前回と同一ならキャッシュをそのまま使い、APIを再呼び出しない
        _prev_answers = session.get("type_quiz_answers")
        _prev_note = str(session.get("type_quiz_challenge_note") or "").strip()
        _same_submission = (
            isinstance(_prev_answers, dict)
            and _prev_answers == answers
            and _prev_note == challenge_note
            and "type_quiz_mini_summary" in session
        )
        if _same_submission:
            _sync_registered_lead_after_result()
            return redirect(url_for("result_view"))

        session.permanent = True
        session["type_quiz_answers"] = answers
        session["type_quiz_best_key"] = best_key
        session["type_quiz_scores_by_key"] = {k: int(v) for k, v in scores.items()}
        session["type_quiz_challenge_note"] = challenge_note
        session.pop("type_quiz_mini_summary", None)
        _append_event("diagnosis_complete")
        rk = _result_kwargs_from_session()
        if rk is None:
            return redirect(url_for("index"))
        _sync_registered_lead_after_result()
        return render_template("result.html", **rk)

    @app.get("/result")
    def result_view():
        """診断セッションがあれば結果を再表示（メール登録後のリダイレクト先など）。"""
        rk = _result_kwargs_from_session()
        if rk is None:
            return redirect(url_for("index"))
        rk["show_line_prompt"] = request.args.get("line_prompt") == "1"
        return render_template("result.html", **rk)

    @app.post("/lead/utage")
    def lead_utage():
        email = (request.form.get("email") or "").strip()
        name = (request.form.get("name") or "").strip()
        err = validate_lead_form(email, name)
        if err:
            flash(err, "error")
            return redirect(url_for("result_view"))

        session["diagnosis_lead_registered"] = True
        session["diagnosis_lead_synced"] = False
        session["lead_email"] = email
        session["lead_name"] = name
        _append_event("lead_register_complete", {"stage": "legacy_result"})
        _sync_registered_lead_after_result()
        flash("登録を受け付けました。次のステップへ進めます。", "success")
        return redirect(url_for("result_view"))

    @app.post("/dev/reset-utage-session")
    def dev_reset_utage_session():
        """テスト用: UTAGE登録セッションをリセットして再登録できるようにする。DEV_MODE=1 のみ有効。"""
        if os.environ.get("DEV_MODE", "").strip() != "1":
            return "forbidden", 403
        for key in ("diagnosis_lead_registered", "diagnosis_lead_synced", "lead_email", "lead_name"):
            session.pop(key, None)
        flash("UTAGE登録セッションをリセットしました。同じメアドで再テストできます。", "success")
        redirect_to = request.form.get("next") or url_for("simple_diagnosis")
        return redirect(redirect_to)

    @app.get("/education")
    def education_bridge():
        """旧ブリッジURL。動画ページに統合したためリダイレクトのみ。"""
        rk = _result_kwargs_from_session()
        if rk is None:
            return redirect(url_for("index"))
        return redirect(url_for("education_video"))

    @app.get("/education/video")
    def education_video():
        rk = _result_kwargs_from_session()
        if rk is None:
            return redirect(url_for("index"))
        return render_template("education_video.html", **rk)

    @app.post("/deep_dive")
    def deep_dive_legacy_redirect():
        """旧「自由記述深掘り」は本格レポートに統合。ブックマーク用POSTもここへ。"""
        return redirect(url_for("premium_ai_report"))

    @app.post("/deep_dive/result")
    def deep_dive_result_legacy_redirect():
        """旧 deep_dive/result は廃止。本格レポートへ誘導。"""
        return redirect(url_for("premium_ai_report"))

    @app.post("/restart")
    def restart():
        _clear_simple_diagnosis_state()
        _clear_30_question_state()
        session.pop("soul_nav_prefilled_turn", None)
        _clear_premium_session()
        return redirect(url_for("simple_diagnosis"))

    @app.get("/premium/ai-report")
    def premium_ai_report():
        best_key = session.get("type_quiz_best_key")
        if not isinstance(best_key, str) or best_key not in SOUL_TYPES:
            return redirect(url_for("index"))

        demo_allowed = os.environ.get("ALLOW_PREMIUM_DEMO", "").strip() == "1"
        access_hint = bool(os.environ.get("PREMIUM_ACCESS_CODE", "").strip())

        if not session.get("premium_unlocked"):
            return render_template(
                "premium_gate.html",
                soul_type=SOUL_TYPES[best_key],
                demo_allowed=demo_allowed,
                access_hint=access_hint,
            )

        report_id = session.get("premium_report_id")
        report: Optional[Dict[str, object]] = None
        if isinstance(report_id, str):
            report = _load_premium_report_file(report_id)

        if report:
            return render_template(
                "premium_report.html",
                soul_type=SOUL_TYPES[best_key],
                report=report,
            )

        return render_template(
            "premium_generate.html",
            soul_type=SOUL_TYPES[best_key],
            error=None,
        )

    @app.post("/premium/ai-report/unlock")
    def premium_ai_report_unlock():
        best_key = session.get("type_quiz_best_key")
        if not isinstance(best_key, str) or best_key not in SOUL_TYPES:
            return redirect(url_for("index"))

        demo_allowed = os.environ.get("ALLOW_PREMIUM_DEMO", "").strip() == "1"
        access_hint = bool(os.environ.get("PREMIUM_ACCESS_CODE", "").strip())

        def _gate_render(error: Optional[str] = None, status: int = 400):
            return (
                render_template(
                    "premium_gate.html",
                    soul_type=SOUL_TYPES[best_key],
                    demo_allowed=demo_allowed,
                    access_hint=access_hint,
                    error=error,
                ),
                status,
            )

        # 定型文だけの「解放済み」状態を作らせない（課金後は必ず API で生成する前提）
        if not _openai_runtime_ready():
            return _gate_render(
                "本格レポートの本文は OpenAI API でのみ生成します。"
                " いまのサーバーでは OPENAI_API_KEY が無いか、openai パッケージが使えません。"
                " 運営側で .env を直し、アプリを再起動してから再度お試しください。",
                503,
            )

        if demo_allowed and request.form.get("demo_unlock") == "1":
            session.permanent = True
            session["premium_unlocked"] = True
            return redirect(url_for("premium_ai_report"))

        code = (request.form.get("access_code") or "").strip()
        expected = os.environ.get("PREMIUM_ACCESS_CODE", "").strip()
        if not expected:
            return _gate_render(
                "サーバーに PREMIUM_ACCESS_CODE が設定されていないため、コードでは解放できません。"
                " 検証中は ALLOW_PREMIUM_DEMO=1 でデモ解放するか、運営側でコードを設定してください。",
                400,
            )

        if code == expected:
            session.permanent = True
            session["premium_unlocked"] = True
            return redirect(url_for("premium_ai_report"))

        return _gate_render("アクセスコードが正しくないか、入力がありません。", 400)

    @app.post("/premium/ai-report/generate")
    def premium_ai_report_generate():
        best_key = session.get("type_quiz_best_key")
        answers = session.get("type_quiz_answers")
        if (
            not session.get("premium_unlocked")
            or not isinstance(best_key, str)
            or best_key not in SOUL_TYPES
            or not isinstance(answers, dict)
        ):
            return redirect(url_for("index"))

        if not _openai_runtime_ready():
            st = SOUL_TYPES[best_key]
            return (
                render_template(
                    "premium_generate.html",
                    soul_type=st,
                    error="OpenAI が利用できないため、本格レポートを生成できません。"
                    " OPENAI_API_KEY と pip install 済みの openai を確認し、アプリを再起動してください。",
                ),
                503,
            )

        raw_scores = session.get("type_quiz_scores_by_key")
        scores_by_key: Dict[str, int] = {}
        if isinstance(raw_scores, dict):
            for k, v in raw_scores.items():
                if isinstance(k, str):
                    try:
                        scores_by_key[k] = int(v)
                    except (TypeError, ValueError):
                        pass

        int_answers: Dict[str, int] = {}
        for q in QUESTIONS:
            v = answers.get(q.key)
            try:
                if v is not None:
                    int_answers[q.key] = int(v)
            except (TypeError, ValueError):
                pass

        st = SOUL_TYPES[best_key]
        sorted_scores = sorted(scores_by_key.items(), key=lambda kv: kv[1], reverse=True)
        scores_by_name = {SOUL_TYPES[k].name: v for k, v in sorted_scores if k in SOUL_TYPES}

        focus = (request.form.get("focus") or "").strip()
        free_text = (request.form.get("free_text") or "").strip()
        qa_lines = _qa_lines_from_session(int_answers)

        try:
            report = generate_premium_ai_report(
                soul_type_name=st.name,
                soul_type_key=st.key,
                soul_summary=st.summary,
                soul_strengths=list(st.strengths),
                soul_pitfalls=list(st.pitfalls),
                scores_by_name=scores_by_name,
                qa_lines=qa_lines,
                likert_choices=LIKERT_CHOICES,
                focus=focus,
                free_text=free_text,
            )
        except Exception as e:
            # premium_report.PremiumReportGenerationError を名前で判定（古い premium_report.py だけがサーバに残ると import が落ちるのを避ける）
            if getattr(e, "__module__", None) == "premium_report" and type(e).__name__ == "PremiumReportGenerationError":
                return (
                    render_template(
                        "premium_generate.html",
                        soul_type=st,
                        error=str(e),
                    ),
                    502,
                )
            raise

        if report is None:
            return (
                render_template(
                    "premium_generate.html",
                    soul_type=st,
                    error="レポートの整形に失敗しました（モデルの返答が想定フォーマットではありません）。もう一度お試しください。",
                ),
                502,
            )

        # 同じユーザー入力で魂のナビの第1ターンも生成し、レポートJSONに保存（二重に書かせない）
        if os.environ.get("PREMIUM_BUNDLE_AUTO_NAV_TURN", "1").strip() != "0":
            bundle_user = _bundle_user_text_for_soul_nav(
                focus,
                free_text,
                str(session.get("type_quiz_challenge_note") or ""),
            )
            if bundle_user:
                try:
                    sorted_sv = sorted(scores_by_key.items(), key=lambda kv: kv[1], reverse=True)
                    display_scores_nav: List[Tuple[str, int]] = [
                        (SOUL_TYPES[k].name, v) for k, v in sorted_sv if k in SOUL_TYPES
                    ]
                    ctx_nav: Dict[str, object] = dict(_soul_type_context_for_nav(best_key, display_scores_nav))
                    _merge_ten_quiz_snapshot(ctx_nav, int_answers)
                    nav_client = openai_client_or_none()
                    nav_model = (os.environ.get("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
                    out, _diag, signals = process_turn(
                        user_text=bundle_user,
                        phase=FlowPhase.INTAKE,
                        openai_client=nav_client,
                        model=nav_model,
                        soul_type_context=ctx_nav,
                    )
                    report["_bundled_first_turn"] = {
                        "user_text": bundle_user,
                        "turn": {
                            "turn_index": 1,
                            "at": utc_now_iso(),
                            "user_input": bundle_user,
                            "phase": FlowPhase.INTAKE.value,
                            "signals": signals,
                            "output": asdict(out),
                        },
                        "next_flow_phase": FlowPhase.MIRROR.value,
                    }
                except Exception:
                    current_app.logger.exception("bundled first soul_nav turn failed")

        report_id = str(uuid.uuid4())
        _save_premium_report_file(report_id, report)
        session.permanent = True
        session["premium_report_id"] = report_id
        _append_event("premium_report_purchase")
        lead_email = str(session.get("lead_email") or "").strip().lower()
        if lead_email:
            enqueue_followup(
                email=lead_email,
                name=str(session.get("lead_name") or ""),
                kind="premium_buyer_to_course",
                context={
                    "course_url": _course_lp_url_external(),
                    "premium_url": _premium_url_external(),
                    "ai_url": _ai_url_external(),
                },
                delay_minutes=_delay_minutes("FOLLOWUP_PREMIUM_TO_COURSE_DELAY_MIN", 12 * 60),
                dedupe_key="premium_to_course_v1",
            )
        return redirect(url_for("premium_ai_report"))

    @app.post("/premium/ai-report/regenerate")
    def premium_ai_report_regenerate():
        """既存レポートを破棄して生成画面へ。"""
        if not session.get("premium_unlocked"):
            return redirect(url_for("index"))
        rid = session.pop("premium_report_id", None)
        _delete_premium_report_file(rid if isinstance(rid, str) else None)
        return redirect(url_for("premium_ai_report"))

    @app.post("/soul-nav/from-diagnosis")
    def soul_nav_from_diagnosis():
        display_scores = _display_scores_from_hidden_form(request.form)
        best_key = _resolve_best_key_from_form(request.form, display_scores)
        if not best_key:
            return redirect(url_for("index"))
        rec = new_session()
        ctx: Dict[str, object] = dict(_soul_type_context_for_nav(best_key, display_scores))
        _merge_ten_quiz_snapshot(ctx, _int_answers_from_request_form(request.form))
        if "ten_quiz_snapshot" not in ctx:
            _merge_ten_quiz_snapshot(ctx, _quiz_from_flask_session())
        rec.soul_type_context = ctx
        save_session(rec)
        session["last_soul_nav_session_id"] = rec.session_id
        return redirect(url_for("soul_nav", session_id=rec.session_id))

    @app.post("/soul-nav/from-premium-report")
    def soul_nav_from_premium_report():
        """本格レポート直後に魂のナビAIへ。レポート要約をモデル文脈に載せてクオリティを上げる。"""
        if not session.get("premium_unlocked"):
            return redirect(url_for("index"))
        report_id = session.get("premium_report_id")
        if not isinstance(report_id, str):
            return redirect(url_for("premium_ai_report"))

        report = _load_premium_report_file(report_id)
        if not report:
            return redirect(url_for("premium_ai_report"))

        display_scores = _display_scores_from_flask_session()
        best_key = session.get("type_quiz_best_key")
        if display_scores is None or not isinstance(best_key, str) or best_key not in SOUL_TYPES:
            return redirect(url_for("index"))

        allowed_nav_phases = {p.value for p in FlowPhase}
        rec = new_session()
        rec.soul_type_context = _soul_nav_context_with_premium(best_key, display_scores, report)
        bundle = report.get("_bundled_first_turn")
        if isinstance(bundle, dict):
            tr = bundle.get("turn")
            outd = tr.get("output") if isinstance(tr, dict) else None
            if isinstance(tr, dict) and isinstance(outd, dict):
                req_k = (
                    "state_organization",
                    "discrepancy",
                    "yesno_hypothesis",
                    "aligned_action",
                    "followup_question",
                )
                if all(isinstance(outd.get(k), str) for k in req_k):
                    rec.turns.append(tr)
                    nfp = bundle.get("next_flow_phase")
                    if isinstance(nfp, str) and nfp in allowed_nav_phases:
                        rec.flow_phase = nfp
                    else:
                        rec.flow_phase = FlowPhase.MIRROR.value
        save_session(rec)
        session["last_soul_nav_session_id"] = rec.session_id
        if rec.turns:
            session["soul_nav_prefilled_turn"] = True
        else:
            session.pop("soul_nav_prefilled_turn", None)
        return redirect(url_for("soul_nav", session_id=rec.session_id))

    @app.get("/soul-nav/from-nav-ai")
    def soul_nav_from_nav_ai():
        nav_result = _nav_diagnosis_result_from_session()
        if nav_result is None:
            flash("先に診断AI（5問）を完了してください。", "error")
            return redirect(url_for("nav_diagnosis_ai.top"))
        rec = new_session()
        rec.soul_type_context = {
            "type_name": "診断AI統合モード",
            "summary": f"{nav_result.verdict_label} / テーマ: {nav_result.theme}",
            "suggested_opener": (
                "診断AIの結果で一番刺さった一文と、まだ違和感が残る点をセットで書いてください。"
            ),
        }
        save_session(rec)
        session["last_soul_nav_session_id"] = rec.session_id
        return redirect(url_for("soul_nav", session_id=rec.session_id))

    @app.get("/soul-nav")
    def soul_nav():
        flow_steps = session_flow_steps()
        sid = request.args.get("session_id", "").strip()
        rec = load_session(sid) if sid else None
        if rec and sid:
            session["last_soul_nav_session_id"] = rec.session_id
        comparison = compare_with_previous(rec) if rec and len(rec.turns) >= 2 else None
        npv = rec.flow_phase if rec else FlowPhase.INTAKE.value
        npl = next((s.title for s in flow_steps if s.phase.value == npv), npv)
        fd, fe = _funnel_for_soul_nav(rec)
        nav_client = openai_client_or_none()
        return render_template(
            "soul_nav.html",
            session=rec,
            comparison=comparison,
            flow_steps=flow_steps,
            next_phase_value=npv,
            next_phase_label=npl,
            api_missing=nav_client is None,
            errors=None,
            premium_unlocked=bool(session.get("premium_unlocked")),
            funnel_done=fd,
            funnel_emphasis=fe,
        )

    @app.get("/soul-nav/turn")
    def soul_nav_turn_get_redirect():
        """POST 専用 URL をアドレスバーで開いたとき用（500 ではなく一覧へ）。"""
        sid = request.args.get("session_id", "").strip()
        if sid:
            return redirect(url_for("soul_nav", session_id=sid))
        return redirect(url_for("soul_nav"))

    @app.post("/soul-nav/turn")
    def soul_nav_turn():
        flow_steps = session_flow_steps()
        sid = request.form.get("session_id", "").strip()
        user_text = (request.form.get("user_text") or "").strip()
        errors: List[str] = []

        if not user_text:
            errors.append("入力が空です。")
        else:
            mc = _soul_nav_min_user_chars()
            if mc > 0 and len(user_text) < mc:
                errors.append(
                    f"入力が短すぎます（目安 {mc} 文字以上）。"
                    "いまの現状・身体感覚・迷いを、もう少し具体的に書いてください。"
                    "このナビは、書いてくれた内容の厚みに応じて真価を発揮します。極端に短いと、意図した精度を出しにくくなります。"
                )

        rec = load_session(sid) if sid else None
        if sid and rec is None:
            errors.append("セッションが見つかりません。新しいセッションから始めてください。")

        if errors:
            r = rec
            npv = r.flow_phase if r else FlowPhase.INTAKE.value
            npl = next((s.title for s in flow_steps if s.phase.value == npv), npv)
            efd, efe = _funnel_for_soul_nav(r)
            err_client = openai_client_or_none()
            return (
                render_template(
                    "soul_nav.html",
                    session=r,
                    comparison=None,
                    flow_steps=flow_steps,
                    next_phase_value=npv,
                    next_phase_label=npl,
                    api_missing=err_client is None,
                    errors=errors,
                    premium_unlocked=bool(session.get("premium_unlocked")),
                    funnel_done=efd,
                    funnel_emphasis=efe,
                ),
                400,
            )

        if rec is None:
            rec = new_session()

        try:
            phase = FlowPhase(rec.flow_phase)
        except ValueError:
            phase = FlowPhase.INTAKE

        client = openai_client_or_none()
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        try:
            out, _diagnosis, signals = process_turn(
                user_text=user_text,
                phase=phase,
                openai_client=client,
                model=model,
                soul_type_context=rec.soul_type_context,
            )
        except Exception:
            current_app.logger.exception("soul_nav process_turn failed")
            npv = rec.flow_phase
            npl = next((s.title for s in flow_steps if s.phase.value == npv), npv)
            efd, efe = _funnel_for_soul_nav(rec)
            err_client = openai_client_or_none()
            return (
                render_template(
                    "soul_nav.html",
                    session=rec,
                    comparison=None,
                    flow_steps=flow_steps,
                    next_phase_value=npv,
                    next_phase_label=npl,
                    api_missing=err_client is None,
                    errors=[
                        "ナビ生成中にエラーが発生しました。設定値（.env）を確認して、"
                        "時間をおいて再度お試しください。"
                    ],
                    premium_unlocked=bool(session.get("premium_unlocked")),
                    funnel_done=efd,
                    funnel_emphasis=efe,
                ),
                500,
            )

        turn_record = {
            "turn_index": len(rec.turns) + 1,
            "at": utc_now_iso(),
            "user_input": user_text,
            "phase": phase.value,
            "signals": signals,
            "output": asdict(out),
        }
        next_phase_val = next_phase(phase).value
        rec.flow_phase = next_phase_val
        try:
            append_turn(rec, turn_record)
            session["last_soul_nav_session_id"] = rec.session_id
        except Exception:
            rec.flow_phase = phase.value
            current_app.logger.exception("soul_nav append_turn / save_session failed")
            npv = rec.flow_phase
            npl = next((s.title for s in flow_steps if s.phase.value == npv), npv)
            efd, efe = _funnel_for_soul_nav(rec)
            err_client = openai_client_or_none()
            return (
                render_template(
                    "soul_nav.html",
                    session=rec,
                    comparison=None,
                    flow_steps=flow_steps,
                    next_phase_value=npv,
                    next_phase_label=npl,
                    api_missing=err_client is None,
                    errors=[
                        "応答の保存に失敗しました。サーバー上で "
                        "<code>data/soul_nav_sessions</code>（または <code>SOUL_NAV_DATA_DIR</code>）の"
                        "書き込み権限を確認してください。"
                    ],
                    premium_unlocked=bool(session.get("premium_unlocked")),
                    funnel_done=efd,
                    funnel_emphasis=efe,
                ),
                500,
            )

        comparison = compare_with_previous(rec)

        if len(rec.turns) > 1:
            session.pop("soul_nav_prefilled_turn", None)

        npv = rec.flow_phase
        npl = next((s.title for s in flow_steps if s.phase.value == npv), npv)
        tfd, tfe = _funnel_for_soul_nav(rec)
        return render_template(
            "soul_nav.html",
            session=rec,
            comparison=comparison,
            flow_steps=flow_steps,
            next_phase_value=npv,
            next_phase_label=npl,
            api_missing=client is None,
            errors=None,
            premium_unlocked=bool(session.get("premium_unlocked")),
            funnel_done=tfd,
            funnel_emphasis=tfe,
        )

    @app.get("/soul-nav/session/<session_id>.json")
    def soul_nav_json(session_id: str):
        rec = load_session(session_id.strip())
        if rec is None:
            return Response("Not Found", status=404, mimetype="text/plain; charset=utf-8")
        payload = json.dumps(rec.to_json_dict(), ensure_ascii=False, indent=2)
        return Response(
            payload,
            status=200,
            mimetype="application/json; charset=utf-8",
        )

    @app.get("/premium/integration-report")
    def premium_integration_report():
        if not session.get("premium_unlocked"):
            flash("統合1枚レポートは深掘りパック解放後に表示されます。", "error")
            return redirect(url_for("premium_ai_report"))

        nav_result = _nav_diagnosis_result_from_session()
        if nav_result is None:
            flash("先に診断AI（5問）を完了してください。", "error")
            return redirect(url_for("nav_diagnosis_ai.top"))

        sid = (request.args.get("session_id") or "").strip()
        if not sid:
            sid = str(session.get("last_soul_nav_session_id") or "").strip()
        if not sid:
            flash("先に魂のナビAIを1ターン以上実行してください。", "error")
            return redirect(url_for("soul_nav"))

        rec = load_session(sid)
        out = _latest_soul_nav_output(rec)
        if rec is None or out is None:
            flash("魂のナビAIの最新結果が見つかりません。もう1ターン実行してください。", "error")
            return redirect(url_for("soul_nav", session_id=sid))

        sheet = _integration_sheet_payload(nav_result, out, sid)
        _append_event("ai_integration_purchase")
        lead_email = str(session.get("lead_email") or "").strip().lower()
        if lead_email:
            enqueue_followup(
                email=lead_email,
                name=str(session.get("lead_name") or ""),
                kind="ai_buyer_to_course",
                context={
                    "course_url": _course_lp_url_external(),
                    "premium_url": _premium_url_external(),
                    "ai_url": _ai_url_external(),
                },
                delay_minutes=_delay_minutes("FOLLOWUP_AI_TO_COURSE_DELAY_MIN", 12 * 60),
                dedupe_key="ai_to_course_v1",
            )
        return render_template(
            "integration_report.html",
            sheet=sheet,
            report_price_label="4,980円",
        )

    @app.post("/track/event")
    def track_event():
        payload = request.get_json(silent=True) or {}
        event_name = str(payload.get("event") or "").strip()
        track_id = str(payload.get("trackId") or "").strip()
        page = str(payload.get("page") or "").strip()
        if event_name:
            _append_event(
                event_name,
                props={"trackId": track_id, "page": page},
            )
            lead_email = str(session.get("lead_email") or "").strip().lower()
            if lead_email and event_name == "course_apply_click":
                mark_state(lead_email, "course_apply_clicked", True)
        return Response("", status=204)

    @app.route("/unsubscribe")
    def unsubscribe():
        email = request.args.get("email", "").strip().lower()
        done = False
        error = ""
        if email:
            if request.args.get("confirm") == "1":
                _add_to_unsubscribe(email)
                done = True
                current_app.logger.info("Unsubscribed: %s", email)
            else:
                import re as _re
                if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
                    error = "メールアドレスが正しくありません。"
        else:
            error = "メールアドレスが指定されていません。"
        return render_template("unsubscribe.html", email=email, done=done, error=error)

    return app
MARKETING_COPY: Dict[str, Dict[str, str]] = {
    "intuition_navi": {
        "empathy": "あなたは感覚で未来を掴むタイプです。",
        "problem": "ただ今、やりたい方向は見えているのに確信が持てない状態になっていませんか？",
        "cause": "これは直感がズレているのではなく、言語化されていないだけです。",
        "solution": "このままだと意思決定が遅れ、本来の流れを逃す可能性があります。",
        "future": "魂のナビセッションでは、あなたの本当の方向性を明確にし、迷いを確信に変えます。",
    },
    "strategy_thinker": {
        "empathy": "あなたは構造で未来を作るタイプです。",
        "problem": "ただ今、情報や選択肢が多くなりすぎて、どれが最適か判断しきれない状態になっていませんか？",
        "cause": "これは能力不足ではなく、判断軸がズレている状態です。",
        "solution": "このままだと時間とエネルギーを無駄に消費します。",
        "future": "魂のナビセッションでは、あなたにとって最適な判断軸を明確にします。",
    },
    "action_breakthrough": {
        "empathy": "あなたは動くことで未来を切り開くタイプです。",
        "problem": "ただ今、行動しているのに思ったほど結果につながらない感覚はありませんか？",
        "cause": "それは努力が足りないのではなく、方向が微妙にズレている可能性があります。",
        "solution": "このままだとエネルギーを消耗し続けます。",
        "future": "魂のナビセッションでは、最短で結果につながる方向を明確にします。",
    },
    "harmony_leader": {
        "empathy": "あなたは人との関係性の中で力を発揮するタイプです。",
        "problem": "ただ今、周囲に合わせすぎて本来の自分の方向が曖昧になっていませんか？",
        "cause": "これは優しさではなく、自己軸が弱まっている状態です。",
        "solution": "このままだと本来の力を発揮できません。",
        "future": "魂のナビセッションでは、自分軸と他者とのバランスを明確にします。",
    },
}



def score_answers(answers: Dict[str, int]) -> Dict[str, int]:
    soul, _, _ = score_diagnosis(answers, QUESTIONS, tuple(SOUL_TYPES.keys()))
    return soul


def score_answers_from_form(form) -> Dict[str, int]:
    answers: Dict[str, int] = {}
    for q in QUESTIONS:
        raw = form.get(q.key, "").strip()
        if not raw:
            continue
        try:
            answers[q.key] = int(raw)
        except ValueError:
            continue
    return score_answers(answers)


def pick_type(scores: Dict[str, int]) -> str:
    best = max(scores.items(), key=lambda kv: (kv[1], -SOUL_TYPE_PRIORITY.index(kv[0])))
    return best[0]


app = create_app()


if __name__ == "__main__":
    # 既定は 127.0.0.1（同一マシンのブラウザのみ）。別端末・LAN から開くときは FLASK_RUN_HOST=0.0.0.0
    _run_host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1").strip() or "127.0.0.1"
    app.run(debug=True, host=_run_host, port=int(os.environ.get("PORT", "5000")))

