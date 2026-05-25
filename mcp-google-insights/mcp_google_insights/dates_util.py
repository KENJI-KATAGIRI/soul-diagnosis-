"""GSC/GA4 共通の「昨日までの7日」と「その直前の7日」。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Tuple


@dataclass(frozen=True)
class WeekWindow:
    start: date
    end: date  # 含む

    @property
    def start_str(self) -> str:
        return self.start.isoformat()

    @property
    def end_str(self) -> str:
        return self.end.isoformat()


def last_two_week_windows(
    *,
    lag_days: int = 1,
) -> Tuple[WeekWindow, WeekWindow]:
    """
    直近7日（終端は通常「昨日」＝GSC の遅延に合わせる）と、その直前の7日。

    lag_days: 終端を今日から何日前にするか（既定1＝昨日まで）。
    """
    end = date.today() - timedelta(days=lag_days)
    current = WeekWindow(start=end - timedelta(days=6), end=end)
    prev_end = current.start - timedelta(days=1)
    previous = WeekWindow(start=prev_end - timedelta(days=6), end=prev_end)
    return current, previous
