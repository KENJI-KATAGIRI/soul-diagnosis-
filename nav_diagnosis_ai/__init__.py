"""魂のナビ診断AI — 5問ウィザード用の質問読込・結果ロジック。"""

from nav_diagnosis_ai.load_questions import Questionnaire, load_questionnaire
from nav_diagnosis_ai.result_logic import QuizResult, compute_result

__all__ = ["Questionnaire", "load_questionnaire", "QuizResult", "compute_result"]
