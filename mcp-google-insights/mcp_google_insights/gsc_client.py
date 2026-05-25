"""Search Console Search Analytics API（読み取り）。"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from googleapiclient.errors import HttpError

from mcp_google_insights.auth_google import search_console_service
from mcp_google_insights.dates_util import WeekWindow


def search_analytics_data_state() -> str:
    """
    Search Analytics API の dataState。

    - ``all`` … 未確定データを含む（直近の日付で 0 になりにくい。週次レビュー向き）
    - ``final`` … 確定のみ（直近数日は 0 や空になりやすい）

    環境変数 ``GSC_SEARCH_ANALYTICS_DATA_STATE`` で ``final`` / ``all`` を指定可能。
    """
    raw = (os.environ.get("GSC_SEARCH_ANALYTICS_DATA_STATE") or "all").strip().lower()
    return raw if raw in ("final", "all") else "all"


def _http_error_message(err: HttpError) -> str:
    try:
        import json

        content = err.content.decode("utf-8", errors="replace")
        data = json.loads(content)
        err_obj = data.get("error") or {}
        details = err_obj.get("details") or []
        nested = err_obj.get("errors") or []
        reasons = [d.get("reason") for d in details if isinstance(d, dict)]
        reasons += [e.get("reason") for e in nested if isinstance(e, dict)]
        msg = err_obj.get("message") or content
    except Exception:
        msg = str(err)
        reasons = []
    base = f"Search Console API エラー ({err.resp.status}): {msg}\n"
    if "accessNotConfigured" in reasons or "accessNotConfigured" in msg:
        base += "・Google Cloud の「その JSON 鍵のプロジェクト」で Search Console API を有効にしてください。\n"
    base += (
        "・サービスアカウントを Search Console の該当プロパティに「ユーザー」として追加したか確認してください。\n"
        "・GSC のサイト URL（URL プレフィックス / ドメイン）が .env の値と完全一致しているか確認してください。"
    )
    return base


def query_search_analytics(
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: Optional[List[str]] = None,
    row_limit: int = 25000,
    start_row: int = 0,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "rowLimit": min(row_limit, 25000),
        "startRow": start_row,
        "dataState": search_analytics_data_state(),
    }
    if dimensions:
        body["dimensions"] = dimensions

    try:
        return (
            search_console_service()
            .searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(_http_error_message(e)) from e


def aggregate_period(site_url: str, window: WeekWindow) -> Dict[str, float]:
    """期間合計: impressions, clicks, ctr, position"""
    resp = query_search_analytics(
        site_url,
        window.start_str,
        window.end_str,
        dimensions=None,
        row_limit=1,
    )
    rows = resp.get("rows") or []
    if not rows:
        return {
            "impressions": 0.0,
            "clicks": 0.0,
            "ctr": 0.0,
            "position": 0.0,
        }
    r = rows[0]
    return {
        "impressions": float(r.get("impressions") or 0),
        "clicks": float(r.get("clicks") or 0),
        "ctr": float(r.get("ctr") or 0),
        "position": float(r.get("position") or 0),
    }


def rows_by_dimension(
    site_url: str,
    window: WeekWindow,
    dimension: str,
    row_limit: int = 200,
) -> List[Dict[str, Any]]:
    resp = query_search_analytics(
        site_url,
        window.start_str,
        window.end_str,
        dimensions=[dimension],
        row_limit=row_limit,
    )
    out: List[Dict[str, Any]] = []
    for row in resp.get("rows") or []:
        keys = row.get("keys") or []
        val = keys[0] if keys else ""
        out.append(
            {
                "key": val,
                "impressions": float(row.get("impressions") or 0),
                "clicks": float(row.get("clicks") or 0),
                "ctr": float(row.get("ctr") or 0),
                "position": float(row.get("position") or 0),
            }
        )
    return out
