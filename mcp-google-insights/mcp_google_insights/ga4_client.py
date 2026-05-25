"""GA4 Data API（REST v1beta / googleapiclient）読み取り。"""

from __future__ import annotations

from typing import Any, Dict, List

from googleapiclient.errors import HttpError

from mcp_google_insights.auth_google import analytics_data_service
from mcp_google_insights.dates_util import WeekWindow


def _property_path(property_id: str) -> str:
    pid = property_id.strip()
    if pid.startswith("properties/"):
        return pid
    return f"properties/{pid}"


def _http_error_message(err: HttpError) -> str:
    try:
        import json

        content = err.content.decode("utf-8", errors="replace")
        data = json.loads(content)
        msg = data.get("error", {}).get("message") or content
    except Exception:
        msg = str(err)
    return (
        f"GA4 Data API エラー ({err.resp.status}): {msg}\n"
        "・サービスアカウントを GA4 のプロパティに「閲覧者」以上で追加したか確認してください。\n"
        "・プロパティ ID（数値）が正しいか確認してください。"
    )


def run_page_report(
    property_id: str,
    window: WeekWindow,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    ページ別: 閲覧回数、セッション、エンゲージメント率、平均エンゲージメント時間（秒）。
    """
    body = {
        "dateRanges": [
            {
                "startDate": window.start_str,
                "endDate": window.end_str,
            }
        ],
        "dimensions": [{"name": "pagePathPlusQueryString"}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "sessions"},
            {"name": "engagementRate"},
            {"name": "averageSessionDuration"},
            {"name": "bounceRate"},
        ],
        "limit": min(limit, 250),
        "orderBys": [
            {"metric": {"metricName": "screenPageViews"}, "desc": True},
        ],
    }
    prop = _property_path(property_id)
    try:
        resp = (
            analytics_data_service()
            .properties()
            .runReport(property=prop, body=body)
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(_http_error_message(e)) from e

    dim_headers = [h.get("name") for h in (resp.get("dimensionHeaders") or [])]
    met_headers = [h.get("name") for h in (resp.get("metricHeaders") or [])]
    rows_out: List[Dict[str, Any]] = []
    for row in resp.get("rows") or []:
        dims = [d.get("value") or "" for d in (row.get("dimensionValues") or [])]
        mets = [m.get("value") or "0" for m in (row.get("metricValues") or [])]
        item: Dict[str, Any] = {}
        for i, name in enumerate(dim_headers):
            item[name] = dims[i] if i < len(dims) else ""
        for i, name in enumerate(met_headers):
            raw = mets[i] if i < len(mets) else "0"
            try:
                item[name] = float(raw)
            except ValueError:
                item[name] = raw
        rows_out.append(item)
    return rows_out


def run_traffic_summary(
    property_id: str,
    window: WeekWindow,
) -> Dict[str, float]:
    """期間合計のざっくり流入・行動（チャネルは最小限：sessionDefaultChannelGrouping の上位のみ別途でも可）。"""
    body = {
        "dateRanges": [
            {
                "startDate": window.start_str,
                "endDate": window.end_str,
            }
        ],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
            {"name": "engagementRate"},
            {"name": "bounceRate"},
        ],
    }
    prop = _property_path(property_id)
    try:
        resp = (
            analytics_data_service()
            .properties()
            .runReport(property=prop, body=body)
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(_http_error_message(e)) from e
    rows = resp.get("rows") or []
    if not rows:
        return {
            "sessions": 0.0,
            "totalUsers": 0.0,
            "screenPageViews": 0.0,
            "engagementRate": 0.0,
            "bounceRate": 0.0,
        }
    mets = rows[0].get("metricValues") or []
    headers = [h.get("name") for h in (resp.get("metricHeaders") or [])]

    def _f(idx: int) -> float:
        if idx >= len(mets):
            return 0.0
        try:
            return float(mets[idx].get("value") or 0)
        except (TypeError, ValueError):
            return 0.0

    out: Dict[str, float] = {}
    for i, name in enumerate(headers):
        out[name] = _f(i)
    return out


def run_channel_breakdown(
    property_id: str,
    window: WeekWindow,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """チャネル別セッション（ざっくり傾向用）。"""
    body = {
        "dateRanges": [
            {
                "startDate": window.start_str,
                "endDate": window.end_str,
            }
        ],
        "dimensions": [{"name": "sessionDefaultChannelGrouping"}],
        "metrics": [{"name": "sessions"}],
        "limit": min(limit, 50),
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    prop = _property_path(property_id)
    try:
        resp = (
            analytics_data_service()
            .properties()
            .runReport(property=prop, body=body)
            .execute()
        )
    except HttpError as e:
        raise RuntimeError(_http_error_message(e)) from e

    out: List[Dict[str, Any]] = []
    for row in resp.get("rows") or []:
        ch = (row.get("dimensionValues") or [{}])[0].get("value") or ""
        sess = (row.get("metricValues") or [{}])[0].get("value") or "0"
        try:
            sv = float(sess)
        except ValueError:
            sv = 0.0
        out.append({"channel": ch, "sessions": sv})
    return out
