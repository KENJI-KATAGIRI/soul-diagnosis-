from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from nav_diagnosis_ai.load_questions import Questionnaire, load_questionnaire
from nav_diagnosis_ai.result_logic import QuizResult, compute_result

SESSION_KEY = "nav_diagnosis_ai_v1"

nav_diagnosis_ai_bp = Blueprint(
    "nav_diagnosis_ai",
    __name__,
    url_prefix="/shindan-ai",
    template_folder="../templates/nav_ai",
)


def _questionnaire() -> Questionnaire:
    return load_questionnaire()


def _quiz_session() -> Dict[str, Any]:
    raw = session.get(SESSION_KEY)
    if not isinstance(raw, dict):
        raw = {}
    if "answers" not in raw or not isinstance(raw["answers"], dict):
        raw["answers"] = {}
    session[SESSION_KEY] = raw
    session.permanent = True
    return raw


def _reset_quiz() -> None:
    session[SESSION_KEY] = {"answers": {}}


def _validate_step(
    q: Dict[str, Any],
    form,
) -> Tuple[Optional[Any], Optional[str]]:
    qid = str(q.get("id", ""))
    inp = q.get("input", "textarea")

    if inp == "textarea":
        max_len = int(q.get("max_length", 2000))
        raw = (form.get(qid) or "").strip()
        if q.get("required") and len(raw) < int(q.get("min_length", 1)):
            return None, "入力してください。"
        if len(raw) > max_len:
            return None, f"{max_len}文字以内にしてください。"
        return raw, None

    if inp == "radio":
        val = (form.get(qid) or "").strip()
        allowed = {str(o.get("value")) for o in (q.get("options") or [])}
        if q.get("required") and val not in allowed:
            return None, "選択してください。"
        return val, None

    if inp == "checkbox":
        vals = form.getlist(qid)
        allowed = {str(o.get("value")) for o in (q.get("options") or [])}
        clean = [v for v in vals if v in allowed]
        min_sel = int(q.get("min_select", 1))
        if len(clean) < min_sel:
            return None, "ひとつ以上選んでください。"
        return clean, None

    return None, "不明な設問タイプです。"


def _answers_complete(answers: Dict[str, Any], total: int) -> bool:
    for step in range(1, total + 1):
        q = _questionnaire().by_step(step)
        if not q:
            return False
        qid = q.get("id")
        if qid not in answers:
            return False
        if q.get("input") == "checkbox":
            v = answers[qid]
            if not isinstance(v, list) or len(v) == 0:
                return False
    return True


@nav_diagnosis_ai_bp.get("/")
def top():
    qz = _questionnaire()
    return render_template("nav_ai/top.html", qz=qz)


@nav_diagnosis_ai_bp.post("/begin")
def begin():
    _reset_quiz()
    return redirect(url_for("nav_diagnosis_ai.question", step=1))


@nav_diagnosis_ai_bp.route("/q/<int:step>", methods=["GET", "POST"])
def question(step: int):
    qz = _questionnaire()
    q = qz.by_step(step)
    if not q:
        return redirect(url_for("nav_diagnosis_ai.top"))

    total = qz.total_steps
    if step < 1 or step > total:
        return redirect(url_for("nav_diagnosis_ai.top"))

    prev_answers = _quiz_session()["answers"]
    for s in range(1, step):
        pq = qz.by_step(s)
        if pq and pq.get("id") not in prev_answers:
            return redirect(url_for("nav_diagnosis_ai.question", step=s))

    error: Optional[str] = None
    qid = str(q.get("id", ""))
    inp = q.get("input", "textarea")

    if request.method == "POST":
        value, err = _validate_step(q, request.form)
        if err:
            error = err
        else:
            prev_answers[qid] = value
            session.modified = True
            if step >= total:
                return redirect(url_for("nav_diagnosis_ai.result"))
            return redirect(url_for("nav_diagnosis_ai.question", step=step + 1))

    current_value = prev_answers.get(qid)
    if error and request.method == "POST":
        if inp == "checkbox":
            current_value = request.form.getlist(qid)
        else:
            current_value = request.form.get(qid, "")

    return render_template(
        "nav_ai/question.html",
        qz=qz,
        q=q,
        step=step,
        total=total,
        progress_ratio=step / total,
        error=error,
        current_value=current_value,
    )


@nav_diagnosis_ai_bp.get("/result")
def result():
    qz = _questionnaire()
    answers = _quiz_session()["answers"]
    if not _answers_complete(answers, qz.total_steps):
        return redirect(url_for("nav_diagnosis_ai.top"))

    res: QuizResult = compute_result(answers, qz.questions)
    return render_template(
        "nav_ai/result.html",
        qz=qz,
        result=res,
        answers=answers,
    )


@nav_diagnosis_ai_bp.get("/premium")
def premium():
    qz = _questionnaire()
    return render_template("nav_ai/premium.html", qz=qz)


@nav_diagnosis_ai_bp.post("/reset")
def reset():
    _reset_quiz()
    return redirect(url_for("nav_diagnosis_ai.top"))
