"""
週次 SEO レポート送信スクリプト

使い方:
  python weekly_report.py              # 全サイトをレポート
  python weekly_report.py --dry-run    # メール送信せず標準出力に表示
  python weekly_report.py --site life-energy-coaching  # 特定サイトのみ
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp_google_insights.tools_impl import get_weekly_site_summary

SITE_KEYS = ["life-energy-coaching", "gaiaarts", "tamashiinavi"]


# ─── データ取得 ──────────────────────────────────────────────────────────────

def fetch_site_data(site_key: str) -> Optional[Dict[str, Any]]:
    try:
        raw = get_weekly_site_summary(site_key)
        return json.loads(raw)
    except Exception as e:
        print(f"[ERROR] {site_key} のデータ取得に失敗: {e}", file=sys.stderr)
        return None


# ─── HTML 整形 ───────────────────────────────────────────────────────────────

def _pct_badge(value: Optional[float]) -> str:
    if value is None:
        return '<span style="color:#888">N/A</span>'
    color = "#27ae60" if value >= 0 else "#e74c3c"
    arrow = "▲" if value >= 0 else "▼"
    return f'<span style="color:{color};font-weight:bold">{arrow} {abs(value):.1f}%</span>'


def _row(label: str, cur: Any, prev: Any, pct: Optional[float]) -> str:
    return (
        f"<tr>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{label}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>{cur:,}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:right'>{prev:,}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;text-align:center'>{_pct_badge(pct)}</td>"
        f"</tr>"
    )


def build_site_html(data: Dict[str, Any]) -> str:
    site_key = data.get("site_key", "")
    period = data.get("period_current", {})
    gsc = data.get("gsc_week_summary", {})
    cur = gsc.get("current", {})
    prev = gsc.get("previous", {})
    wow = data.get("week_over_week_change_percent", {}) or {}
    ga4 = data.get("ga4") or {}
    improvements = data.get("improvement_candidates", [])
    ctr_candidates = data.get("ctr_improvement_candidates", [])
    column_topics = data.get("column_topic_candidates", [])
    link_candidates = data.get("internal_link_candidates", [])

    # GSC サマリーテーブル
    gsc_table = f"""
    <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
      <thead>
        <tr style="background:#f4f6f9">
          <th style="padding:8px 12px;text-align:left">指標</th>
          <th style="padding:8px 12px;text-align:right">今週</th>
          <th style="padding:8px 12px;text-align:right">前週</th>
          <th style="padding:8px 12px;text-align:center">前週比</th>
        </tr>
      </thead>
      <tbody>
        {_row("表示回数（インプレッション）", cur.get("impressions",0), prev.get("impressions",0), wow.get("impressions"))}
        {_row("クリック数", cur.get("clicks",0), prev.get("clicks",0), wow.get("clicks"))}
        <tr>
          <td style="padding:6px 12px;border-bottom:1px solid #eee">CTR</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee;text-align:right">{gsc.get("ctr_percent_current",0):.2f}%</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee;text-align:right">{round((prev.get("ctr") or 0)*100,2):.2f}%</td>
          <td style="padding:6px 12px;border-bottom:1px solid #eee;text-align:center">{_pct_badge(wow.get("ctr"))}</td>
        </tr>
        <tr>
          <td style="padding:6px 12px">平均掲載順位</td>
          <td style="padding:6px 12px;text-align:right">{round(cur.get("position",0),1)}</td>
          <td style="padding:6px 12px;text-align:right">{round(prev.get("position",0),1)}</td>
          <td style="padding:6px 12px;text-align:center"><span style="color:#888">（小さいほど良）</span></td>
        </tr>
      </tbody>
    </table>
    """

    # GA4 サマリー
    ga4_html = ""
    if ga4 and "error" not in ga4:
        cur_sum = ga4.get("traffic_summary_current", {})
        prev_sum = ga4.get("traffic_summary_previous", {})
        sessions_wow = ga4.get("sessions_wow_percent")
        channels = ga4.get("channel_sessions", [])
        low_eng = ga4.get("low_engagement_pages", [])

        channel_rows = "".join(
            f"<tr><td style='padding:4px 10px'>{c.get('channel','')}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{c.get('sessions',0):,}</td></tr>"
            for c in channels
        )

        low_eng_rows = "".join(
            f"<tr><td style='padding:4px 10px;font-size:12px;color:#555'>{p.get('pagePath','')}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{p.get('screenPageViews',0)}</td>"
            f"<td style='padding:4px 10px;text-align:right'>{round(float(p.get('engagementRate') or 0)*100,1)}%</td></tr>"
            for p in low_eng
        ) if low_eng else "<tr><td colspan='3' style='padding:4px 10px;color:#888'>なし</td></tr>"

        ga4_html = f"""
        <h3 style="color:#2c3e50;margin-top:24px">GA4 アクセス概要</h3>
        <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
          <thead>
            <tr style="background:#f4f6f9">
              <th style="padding:8px 12px;text-align:left">指標</th>
              <th style="padding:8px 12px;text-align:right">今週</th>
              <th style="padding:8px 12px;text-align:right">前週</th>
              <th style="padding:8px 12px;text-align:center">前週比</th>
            </tr>
          </thead>
          <tbody>
            {_row("セッション数", cur_sum.get("sessions",0), prev_sum.get("sessions",0), sessions_wow)}
            {_row("ページビュー", cur_sum.get("screenPageViews",0), prev_sum.get("screenPageViews",0), None)}
            {_row("ユーザー数", cur_sum.get("totalUsers",0), prev_sum.get("totalUsers",0), None)}
          </tbody>
        </table>

        <h4 style="color:#555;margin-top:16px">流入チャネル内訳（今週）</h4>
        <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
          <thead><tr style="background:#f4f6f9">
            <th style="padding:6px 10px;text-align:left">チャネル</th>
            <th style="padding:6px 10px;text-align:right">セッション</th>
          </tr></thead>
          <tbody>{channel_rows}</tbody>
        </table>

        <h4 style="color:#555;margin-top:16px">エンゲージメント低ページ（改善候補）</h4>
        <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
          <thead><tr style="background:#fff3cd">
            <th style="padding:6px 10px;text-align:left">ページ</th>
            <th style="padding:6px 10px;text-align:right">PV</th>
            <th style="padding:6px 10px;text-align:right">エンゲージ率</th>
          </tr></thead>
          <tbody>{low_eng_rows}</tbody>
        </table>
        """
    elif ga4 and "error" in ga4:
        ga4_html = f'<p style="color:#e74c3c">GA4 エラー: {ga4["error"]}</p>'

    # 改善アラート
    alert_items = "".join(f"<li style='margin-bottom:6px'>{i}</li>" for i in improvements)

    # CTR 改善候補
    ctr_rows = "".join(
        f"<tr><td style='padding:4px 10px;font-size:12px'>{q.get('query','')}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{q.get('impressions',0):,}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{q.get('ctr_percent',0):.2f}%</td>"
        f"<td style='padding:4px 10px;text-align:right'>{round(q.get('position',0),1)}</td>"
        f"<td style='padding:4px 10px;font-size:11px;color:#666'>{q.get('hint','')}</td></tr>"
        for q in ctr_candidates
    ) if ctr_candidates else "<tr><td colspan='5' style='padding:4px 10px;color:#888'>なし</td></tr>"

    # コラム題材候補
    topic_rows = "".join(
        f"<tr><td style='padding:4px 10px;font-size:12px'>{q.get('query','')}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{q.get('impressions',0):,}</td>"
        f"<td style='padding:4px 10px;font-size:11px;color:#2980b9'>{q.get('suggestion_tag','')}</td></tr>"
        for q in column_topics
    ) if column_topics else "<tr><td colspan='3' style='padding:4px 10px;color:#888'>なし</td></tr>"

    # 内部リンク候補
    link_rows = "".join(
        f"<tr><td style='padding:4px 10px;font-size:12px;color:#555'>{p.get('page','')}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{p.get('impressions',0):,}</td>"
        f"<td style='padding:4px 10px;text-align:right'>{p.get('ctr_percent',0):.2f}%</td></tr>"
        for p in link_candidates
    ) if link_candidates else "<tr><td colspan='3' style='padding:4px 10px;color:#888'>なし</td></tr>"

    site_label = {
        "life-energy-coaching": "Life Energy Coaching",
        "gaiaarts": "Gaia Arts",
        "tamashiinavi": "魂のナビ診断",
    }.get(site_key, site_key)

    return f"""
    <div style="background:#fff;border:1px solid #dde;border-radius:8px;padding:24px;margin-bottom:32px">
      <h2 style="color:#2c3e50;border-left:4px solid #3498db;padding-left:12px;margin-top:0">
        {site_label}
      </h2>
      <p style="color:#666;font-size:13px">集計期間（今週）: {period.get("start","")} 〜 {period.get("end","")}</p>

      <h3 style="color:#2c3e50">Search Console サマリー</h3>
      {gsc_table}

      {ga4_html}

      <h3 style="color:#e67e22;margin-top:24px">今週のアラート・注目点</h3>
      <ul style="background:#fff9f0;padding:16px 24px;border-radius:6px">{alert_items}</ul>

      <h3 style="color:#2c3e50;margin-top:24px">CTR 改善候補クエリ</h3>
      <p style="font-size:12px;color:#666">表示回数は多いがCTRが低いクエリ — タイトル・メタディスクリプションを見直す優先候補</p>
      <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
        <thead><tr style="background:#fef9e7">
          <th style="padding:6px 10px;text-align:left">クエリ</th>
          <th style="padding:6px 10px;text-align:right">表示回数</th>
          <th style="padding:6px 10px;text-align:right">CTR</th>
          <th style="padding:6px 10px;text-align:right">順位</th>
          <th style="padding:6px 10px;text-align:left">ヒント</th>
        </tr></thead>
        <tbody>{ctr_rows}</tbody>
      </table>

      <h3 style="color:#2c3e50;margin-top:24px">コラム・記事題材候補</h3>
      <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
        <thead><tr style="background:#eaf4fb">
          <th style="padding:6px 10px;text-align:left">クエリ</th>
          <th style="padding:6px 10px;text-align:right">表示回数</th>
          <th style="padding:6px 10px;text-align:left">タグ</th>
        </tr></thead>
        <tbody>{topic_rows}</tbody>
      </table>

      <h3 style="color:#2c3e50;margin-top:24px">内部リンク強化候補ページ</h3>
      <table style="border-collapse:collapse;width:100%;margin-bottom:8px">
        <thead><tr style="background:#eafaf1">
          <th style="padding:6px 10px;text-align:left">ページ URL</th>
          <th style="padding:6px 10px;text-align:right">表示回数</th>
          <th style="padding:6px 10px;text-align:right">CTR</th>
        </tr></thead>
        <tbody>{link_rows}</tbody>
      </table>
    </div>
    """


def build_html(sites_data: List[Dict[str, Any]]) -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    bodies = "".join(build_site_html(d) for d in sites_data)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head><meta charset="utf-8"><title>週次 SEO レポート {today}</title></head>
<body style="font-family:'Helvetica Neue',Arial,sans-serif;background:#f0f2f5;padding:24px;color:#333">
  <div style="max-width:800px;margin:0 auto">
    <div style="background:#2c3e50;color:#fff;padding:20px 24px;border-radius:8px 8px 0 0;margin-bottom:24px">
      <h1 style="margin:0;font-size:20px">週次 SEO レポート</h1>
      <p style="margin:4px 0 0;font-size:13px;opacity:0.8">{today} 自動送信</p>
    </div>

    {bodies}

    <div style="background:#ecf0f1;padding:16px 24px;border-radius:0 0 8px 8px;font-size:12px;color:#666;margin-top:-16px">
      このメールは mcp-google-insights の weekly_report.py により自動送信されています。<br>
      データソース: Google Search Console / Google Analytics 4
    </div>
  </div>
</body>
</html>"""


# ─── メール送信 ──────────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str) -> None:
    host = os.environ.get("SMTP_HOST", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    to_raw = os.environ.get("REPORT_TO", "").strip()
    recipients = [r.strip() for r in to_raw.split(",") if r.strip()]

    if not host:
        raise ValueError(".env の SMTP_HOST が未設定です")
    if not user or not password:
        raise ValueError(".env の SMTP_USER / SMTP_PASSWORD が未設定です")
    if not recipients:
        raise ValueError(".env の REPORT_TO が未設定です")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(user, recipients, msg.as_string())

    print(f"[OK] メール送信完了 → {', '.join(recipients)}")


# ─── エントリポイント ────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="週次 SEO レポートをメール送信")
    parser.add_argument("--dry-run", action="store_true", help="メール送信せず HTML を標準出力に表示")
    parser.add_argument("--site", help="特定のサイトのみ実行（例: gaiaarts）")
    args = parser.parse_args()

    target_sites = [args.site] if args.site else SITE_KEYS

    print(f"[INFO] レポート生成開始 ({', '.join(target_sites)})")
    sites_data: List[Dict[str, Any]] = []
    for site_key in target_sites:
        print(f"[INFO] {site_key} のデータ取得中...")
        data = fetch_site_data(site_key)
        if data:
            sites_data.append(data)

    if not sites_data:
        print("[ERROR] 全サイトのデータ取得に失敗しました。終了します。", file=sys.stderr)
        sys.exit(1)

    today = datetime.now().strftime("%Y/%m/%d")
    subject = f"【週次 SEO レポート】{today}"
    html = build_html(sites_data)

    if args.dry_run:
        print(html)
        return

    send_email(subject, html)


if __name__ == "__main__":
    main()
