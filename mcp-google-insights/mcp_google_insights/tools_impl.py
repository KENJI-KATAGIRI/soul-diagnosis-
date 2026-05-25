"""MCP 各 tool の実装本体（JSON 文字列を返す）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from mcp_google_insights.config import require_ga4_property, resolve_site
from mcp_google_insights.dates_util import last_two_week_windows
from mcp_google_insights import ga4_client, gsc_client


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _pct_change(cur: float, prev: float) -> Optional[float]:
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100.0, 2)


def get_search_console_summary(site_key: str) -> str:
    site = resolve_site(site_key)
    current, previous = last_two_week_windows()
    cur = gsc_client.aggregate_period(site.gsc_site_url, current)
    prev = gsc_client.aggregate_period(site.gsc_site_url, previous)
    return _json(
        {
            "site_key": site.key,
            "gsc_site_url": site.gsc_site_url,
            "gsc_search_analytics_data_state": gsc_client.search_analytics_data_state(),
            "current_week": {
                "start": current.start_str,
                "end": current.end_str,
                **cur,
                "ctr_percent": round(cur["ctr"] * 100, 3),
            },
            "previous_week": {
                "start": previous.start_str,
                "end": previous.end_str,
                **prev,
                "ctr_percent": round(prev["ctr"] * 100, 3),
            },
            "week_over_week_change_percent": {
                "impressions": _pct_change(cur["impressions"], prev["impressions"]),
                "clicks": _pct_change(cur["clicks"], prev["clicks"]),
                "ctr": _pct_change(cur["ctr"], prev["ctr"])
                if prev["ctr"] > 0
                else None,
            },
            "average_position_delta_vs_previous_week": round(
                cur["position"] - prev["position"], 3
            ),
            "note_position": "平均掲載順位は数値が下がるほど改善（上位化）です。",
        }
    )


def get_search_console_pages(site_key: str, row_limit: int = 100) -> str:
    site = resolve_site(site_key)
    current, _ = last_two_week_windows()
    rows = gsc_client.rows_by_dimension(
        site.gsc_site_url, current, "page", row_limit=min(row_limit, 500)
    )
    return _json(
        {
            "site_key": site.key,
            "gsc_site_url": site.gsc_site_url,
            "gsc_search_analytics_data_state": gsc_client.search_analytics_data_state(),
            "period": {"start": current.start_str, "end": current.end_str},
            "rows": rows,
        }
    )


def get_search_console_queries(site_key: str, row_limit: int = 100) -> str:
    site = resolve_site(site_key)
    current, _ = last_two_week_windows()
    rows = gsc_client.rows_by_dimension(
        site.gsc_site_url, current, "query", row_limit=min(row_limit, 500)
    )
    return _json(
        {
            "site_key": site.key,
            "gsc_site_url": site.gsc_site_url,
            "gsc_search_analytics_data_state": gsc_client.search_analytics_data_state(),
            "period": {"start": current.start_str, "end": current.end_str},
            "rows": rows,
        }
    )


def get_ga4_page_report(site_key: str, page_row_limit: int = 40) -> str:
    site = resolve_site(site_key)
    pid = require_ga4_property(site)
    current, previous = last_two_week_windows()
    cur_pages = ga4_client.run_page_report(pid, current, limit=page_row_limit)
    prev_pages = ga4_client.run_page_report(pid, previous, limit=page_row_limit)
    cur_sum = ga4_client.run_traffic_summary(pid, current)
    prev_sum = ga4_client.run_traffic_summary(pid, previous)
    channels = ga4_client.run_channel_breakdown(pid, current, limit=8)
    return _json(
        {
            "site_key": site.key,
            "ga4_property": pid if str(pid).startswith("properties/") else f"properties/{pid}",
            "current_week": {
                "start": current.start_str,
                "end": current.end_str,
                "traffic_summary": cur_sum,
                "top_pages": cur_pages,
                "channel_sessions": channels,
            },
            "previous_week": {
                "start": previous.start_str,
                "end": previous.end_str,
                "traffic_summary": prev_sum,
                "top_pages": prev_pages,
            },
            "week_over_week_change_percent": {
                "sessions": _pct_change(cur_sum.get("sessions", 0), prev_sum.get("sessions", 0)),
                "screenPageViews": _pct_change(
                    cur_sum.get("screenPageViews", 0), prev_sum.get("screenPageViews", 0)
                ),
                "totalUsers": _pct_change(
                    cur_sum.get("totalUsers", 0), prev_sum.get("totalUsers", 0)
                ),
            },
        }
    )


def _ctr_candidates(
    queries: List[Dict[str, Any]], site_ctr: float, min_impressions: float = 80.0
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    threshold = max(site_ctr * 0.45, 0.005)
    for q in queries:
        imp = q.get("impressions") or 0
        ctr = q.get("ctr") or 0
        pos = q.get("position") or 99
        if imp >= min_impressions and ctr <= threshold and pos <= 25:
            out.append(
                {
                    "query": q.get("key"),
                    "impressions": imp,
                    "ctr_percent": round(ctr * 100, 3),
                    "position": round(pos, 2),
                    "hint": "タイトル・メタディスクリプション・見出しと検索意図のすり合わせ",
                }
            )
    return out[:15]


def _column_candidates(queries: List[Dict[str, Any]], top_n: int = 12) -> List[Dict[str, Any]]:
    """クエリ上位を「コラム題材候補」として列挙（ルールベース）。"""
    hints = ("とは", "どう", "方法", "意味", "なぜ", "いくら", "違い", "メリット")
    out: List[Dict[str, Any]] = []
    for q in queries[:top_n]:
        text = str(q.get("key") or "")
        tag = "検索ボリューム大（題材化の検討）"
        if any(h in text for h in hints):
            tag = "情報探索クエリ（解説コラム向き）"
        out.append(
            {
                "query": text,
                "impressions": q.get("impressions"),
                "clicks": q.get("clicks"),
                "suggestion_tag": tag,
            }
        )
    return out


def _internal_link_candidates(
    pages: List[Dict[str, Any]], site_ctr: float, min_impressions: float = 120.0
) -> List[Dict[str, Any]]:
    """表示は多いが CTR がサイト平均を大きく下回る URL → 回遊・内部リンク強化候補。"""
    out: List[Dict[str, Any]] = []
    threshold = max(site_ctr * 0.55, 0.008)
    for p in pages:
        imp = p.get("impressions") or 0
        ctr = p.get("ctr") or 0
        if imp >= min_impressions and ctr < threshold:
            out.append(
                {
                    "page": p.get("key"),
                    "impressions": imp,
                    "ctr_percent": round(ctr * 100, 3),
                    "position": round(float(p.get("position") or 0), 2),
                    "hint": "サイト内の関連ページからの内部リンク追加・導線の明確化",
                }
            )
    return out[:15]


def get_weekly_site_summary(site_key: str) -> str:
    site = resolve_site(site_key)
    current, previous = last_two_week_windows()
    cur_g = gsc_client.aggregate_period(site.gsc_site_url, current)
    prev_g = gsc_client.aggregate_period(site.gsc_site_url, previous)
    pages = gsc_client.rows_by_dimension(
        site.gsc_site_url, current, "page", row_limit=80
    )
    queries = gsc_client.rows_by_dimension(
        site.gsc_site_url, current, "query", row_limit=80
    )
    site_ctr = cur_g["ctr"] or 0.0001

    ga4_block: Optional[Dict[str, Any]] = None
    try:
        pid = require_ga4_property(site)
        cur_pages = ga4_client.run_page_report(pid, current, limit=25)
        cur_sum = ga4_client.run_traffic_summary(pid, current)
        prev_sum = ga4_client.run_traffic_summary(pid, previous)
        channels = ga4_client.run_channel_breakdown(pid, current, limit=6)
        ga4_block = {
            "traffic_summary_current": cur_sum,
            "traffic_summary_previous": prev_sum,
            "channel_sessions": channels,
            "top_pages_current": cur_pages[:15],
            "sessions_wow_percent": _pct_change(
                cur_sum.get("sessions", 0), prev_sum.get("sessions", 0)
            ),
        }
        # GA4 で閲覧はあるが相対的にエンゲージが低いページ
        low_eng = [
            r
            for r in cur_pages
            if r.get("screenPageViews", 0) >= 20
            and float(r.get("engagementRate") or 0) < 0.45
        ][:10]
        ga4_block["low_engagement_pages"] = low_eng
    except Exception as e:
        ga4_block = {"error": str(e)}

    improvements: List[str] = []
    if _pct_change(cur_g["clicks"], prev_g["clicks"]) is not None:
        cw = _pct_change(cur_g["clicks"], prev_g["clicks"])
        iw = _pct_change(cur_g["impressions"], prev_g["impressions"])
        if cw is not None and cw < -5:
            improvements.append(
                f"クリック数が前週比 {cw}% 。表示数の変化は {iw}% 。順位・スニペット・新規インデックスを確認。"
            )
        if iw is not None and iw < -8:
            improvements.append(
                f"表示回数が前週比 {iw}% 減。季節要因・アルゴリズム・インデックス状況を確認。"
            )
    if not improvements:
        improvements.append(
            "大きな急変は見えにくい週です。CTR 改善候補クエリと内部リンク候補を優先レビューしてください。"
        )

    gsc_zero = (cur_g.get("impressions") or 0) == 0 and (cur_g.get("clicks") or 0) == 0
    gsc_zero_hints: List[str] = []
    if gsc_zero:
        gsc_zero_hints.extend(
            [
                "APIは成功しているが、この期間・この gsc_site_url で検索パフォーマンスが0です。Search Consoleの「検索パフォーマンス」で同じ日付範囲に数字があるか照合してください。",
                "プロパティ表記（https://…/ と sc-domain:…）が .env の GSC_SITE_* と完全一致しているか確認してください（www 有無も別プロパティです）。",
                "確定データのみにしたい場合は環境変数 GSC_SEARCH_ANALYTICS_DATA_STATE=final（直近が0になりやすい）です。既定は all です。",
            ]
        )

    payload = {
        "site_key": site.key,
        "gsc_site_url": site.gsc_site_url,
        "gsc_search_analytics_data_state": gsc_client.search_analytics_data_state(),
        "period_current": {"start": current.start_str, "end": current.end_str},
        "gsc_week_summary": {
            "current": cur_g,
            "previous": prev_g,
            "ctr_percent_current": round(cur_g["ctr"] * 100, 3),
        },
        "gsc_when_all_metrics_zero_hints": gsc_zero_hints,
        "ga4": ga4_block,
        "improvement_candidates": improvements,
        "ctr_improvement_candidates": _ctr_candidates(queries, site_ctr),
        "column_topic_candidates": _column_candidates(queries),
        "internal_link_candidates": _internal_link_candidates(pages, site_ctr),
    }
    return _json(payload)
