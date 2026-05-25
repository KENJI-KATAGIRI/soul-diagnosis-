from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Questionnaire:
    version: int
    app_title: str
    tagline: str
    total_steps: int
    questions: List[Dict[str, Any]]
    source_path: str

    def by_step(self, step: int) -> Optional[Dict[str, Any]]:
        for q in self.questions:
            if int(q.get("step", 0)) == step:
                return q
        return None

    def by_id(self, qid: str) -> Optional[Dict[str, Any]]:
        for q in self.questions:
            if q.get("id") == qid:
                return q
        return None


def default_questions_path() -> Path:
    override = os.environ.get("NAV_DIAGNOSIS_AI_QUESTIONS", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "questions.json"


def load_questionnaire(path: Optional[Path] = None) -> Questionnaire:
    p = path or default_questions_path()
    raw = json.loads(p.read_text(encoding="utf-8"))
    return Questionnaire(
        version=int(raw.get("version", 1)),
        app_title=str(raw.get("app_title", "魂のナビ診断AI")),
        tagline=str(raw.get("tagline", "")),
        total_steps=int(raw.get("total_steps", len(raw.get("questions", [])))),
        questions=list(raw.get("questions", [])),
        source_path=str(p),
    )
