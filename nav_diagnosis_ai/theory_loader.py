from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


@lru_cache(maxsize=1)
def load_theory_snippets() -> Dict[str, Any]:
    path = Path(__file__).resolve().parent / "theory_snippets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def q2_theory_key(answer: str) -> str:
    m = {
        "must": "must",
        "should": "should",
        "want": "want",
        "want_but_scared": "want_but_scared",
        "mixed": "mixed",
    }
    return m.get(str(answer).strip(), "")
