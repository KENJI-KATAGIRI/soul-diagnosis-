from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List, Tuple


def _s(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _strip_diagnosis_email_promo_footer(body: str) -> str:
    """末尾の講座LP案内・診断トップリンクを除去（旧本文・キューに残った文字列も送らない）。"""
    lines = body.split("\n")
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        st = raw.strip()
        if st.startswith("■ 講座のご案内"):
            i += 1
            while i < n:
                t = lines[i].strip()
                if not t or t.startswith("■ ") or t.startswith("━━"):
                    break
                i += 1
            continue
        if st.startswith("■ 診断トップ"):
            i += 1
            while i < n:
                t = lines[i].strip()
                if not t or t.startswith("■ ") or t.startswith("━━"):
                    break
                i += 1
            continue
        out.append(raw)
        i += 1
    text = "\n".join(out).rstrip()
    return text + "\n" if text else ""


def _append_links_and_video_cta(lines: List[str], type_name: str, links: Dict[str, str]) -> None:
    """LINE登録→動画のリンクブロックのみ（本文末尾）。講座LP・診断トップは付けない。"""
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("■ 次のステップ（LINE登録 → 動画）")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    video = _s(links.get("guide_video_url"))
    vtitle = _s(links.get("guide_video_title")) or "LINE登録後に、整え方の動画を受け取る"

    if video:
        lines.append(
            f"この結果を読んで「もう少し具体的に知りたい」「どう動けばいいかわからない」と感じた方へ。\n"
            f"{type_name}の傾向とズレの整理は、動画でもう一段掘り下げてお話しています。\n"
            f"まずは下のページからLINEに登録いただくと、登録後の導線で動画をご覧いただけます。\n"
            f"先ほどの結果と照らし合わせながら、進めてみてください。\n"
        )
        lines.append(f"▶ {vtitle}\n{video}")
        lines.append("")


def _append_issuer_footer(lines: List[str], unsubscribe_url: str = "") -> None:
    """発行者情報フッターをメール末尾に追加する。"""
    while lines and lines[-1] == "":
        lines.pop()
    sep = "━" * 30
    footer = [
        "",
        sep,
        "【発行者情報】",
        "屋号：Gaia Arts Creation",
        "代表者：片桐 健治",
        "所在地：愛知県名古屋市中区",
        "　※ご請求があった場合、遅滞なく開示いたします。",
        "メール：info@tamashiinavi.com",
        "HP：https://gaiaarts.org",
        "",
        "プライバシーポリシー：https://lp.tamashiinavi.com/p/polisy",
        "特定商取引法に基づく表記：https://lp.tamashiinavi.com/p/tokusyo",
        "会社概要：https://lp.tamashiinavi.com/p/co",
    ]
    if unsubscribe_url:
        footer.append(f"配信停止はこちら：{unsubscribe_url}")
    footer.append(sep)
    lines.extend(footer)


def format_diagnosis_result_minimal_fallback(
    *,
    recipient_name: str,
    type_name: str,
    one_liner: str,
    insight: Any,
    marketing: Dict[str, str],
    display_scores: List[Tuple[str, int]],
    max_score: int,
    links: Dict[str, str],
) -> str:
    """セッションからフル結果を組めないときの簡易版（タイプ・主要ブロック・スコア・リンク）。"""

    def _co(attr: str) -> str:
        return _s(getattr(insight, attr, None))

    lines: List[str] = []
    rn = _s(recipient_name)
    if rn:
        lines.extend(
            [
                f"{rn} 様",
                "",
                "このメールには、無料診断の結果をテキストでお届けしています（簡易版です）。",
                "",
            ]
        )
    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "魂のナビ診断｜結果（簡易版）",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"■ 魂タイプ：{type_name}",
            "",
            one_liner or "（タイプの一言要約）",
            "",
        ]
    )
    if display_scores and max_score > 0:
        lines.append("■ スコア内訳（目安）")
        for name, sc in display_scores:
            try:
                iv = int(sc)
            except (TypeError, ValueError):
                iv = 0
            pct = min(100, max(0, int(iv / max_score * 100)))
            lines.append(f"  ・{name} … {iv}（バー目安 {pct}%）")
        lines.append("")
    lines.extend(
        [
            "■ いまの状態（参考）",
            _co("alignment_state"),
            _s(marketing.get("empathy")),
            "",
            "■ よくある悩み / ズレやすい理由",
            _s(marketing.get("problem")),
            _co("misalignment_reason"),
            "",
            "■ 今すぐできる一歩",
            _co("next_action"),
            "",
            "■ 意識レベル・エネルギー（参考）",
            f"意識レベル目安：{_co('consciousness_level')}（{_co('consciousness_label')} / {_co('consciousness_emotion')}）",
            f"エネルギー：{_co('energy_score')}点",
            "",
            "※目安であり医療・心理の診断ではありません。",
            "",
        ]
    )
    _append_links_and_video_cta(lines, type_name, links)
    _append_issuer_footer(lines, unsubscribe_url=_s(links.get("unsubscribe_url")))
    return "\n".join(lines)


def format_diagnosis_result_plain_text(
    rk: Dict[str, Any],
    *,
    links: Dict[str, str],
    recipient_name: str = "",
) -> str:
    """診断結果ページ（result.html）と同じ構成をプレーンテキストにする。"""
    soul_type = rk.get("soul_type")
    type_name = _s(getattr(soul_type, "name", None)) or "（不明）"
    type_summary = _s(getattr(soul_type, "summary", None))

    rs = rk.get("result_sections") or {}
    if not isinstance(rs, dict):
        rs = {}
    consciousness = rk.get("consciousness")

    def _co(name: str) -> str:
        if consciousness is None:
            return ""
        return _s(getattr(consciousness, name, None))

    lines: List[str] = []
    rn = _s(recipient_name)
    if rn:
        lines.extend([f"{rn} 様", ""])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "魂のナビ診断｜結果",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"魂タイプ：{type_name}",
        "",
        _s(rs.get("one_liner")) or type_summary,
        "",
    ])

    # タイプ別スコア（最大余剰法で合計30に正規化）
    scores = rk.get("scores") or []
    if isinstance(scores, list) and scores:
        raw_names = [str(n) for n, _ in scores]
        raw_vals = []
        for _, sc in scores:
            try:
                raw_vals.append(int(sc))
            except (TypeError, ValueError):
                raw_vals.append(0)
        score_total = sum(raw_vals)
        if score_total > 0:
            exact = [v / score_total * 30 for v in raw_vals]
            floored = [int(v) for v in exact]
            remainder = 30 - sum(floored)
            order = sorted(range(len(exact)), key=lambda i: exact[i] - floored[i], reverse=True)
            for i in range(remainder):
                floored[order[i]] += 1
            scaled_vals = floored
        else:
            scaled_vals = [0] * len(raw_vals)
        lines.append("■ タイプ別スコア（合計30）")
        for nm, sv in zip(raw_names, scaled_vals):
            lines.append(f"  {nm}：{sv}")
        lines.append("")

    # 先に結論
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "■ 先に結論",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"今の状態：{_co('alignment_state')}",
        "",
        f"起きやすいこと：{_s(rs.get('why_misaligned')) or _co('misalignment_reason')}",
        "",
        f"最初の一歩：{_s(rs.get('small_step')) or _co('next_action')}",
        "",
    ])

    # いまの位置（推定）
    pp = rk.get("position_profile") or {}
    if isinstance(pp, dict) and pp.get("phase_title"):
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ いまの位置（推定）",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"変容フェーズ：{_s(pp.get('phase_title'))}",
            _s(pp.get("phase_body")),
            "",
            f"ナビの寄り：{_s(pp.get('navi_title'))}",
            _s(pp.get("navi_body")),
            "",
        ])
        sub = _s(pp.get("sub_type_name"))
        if sub:
            lines.extend([f"副次に近いタイプ：{sub}（メインタイプと併せて読むと解像度が上がります）", ""])

    # あなた向けミニ要約
    mini = _s(rk.get("mini_summary_text"))
    if mini:
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ あなた向けミニ要約",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            mini,
            "",
        ])

    # テーマ別の傾向
    theme_insights = rs.get("theme_insights")
    if isinstance(theme_insights, dict):
        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "■ テーマ別の傾向",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ])
        for label, key in [("人間関係", "relationships"), ("仕事", "work"), ("パートナー", "partner")]:
            items = theme_insights.get(key)
            if isinstance(items, list) and items:
                lines.append(f"【{label}】")
                for item in items:
                    lines.append(f"  ・{_s(item)}")
                lines.append("")

    _append_links_and_video_cta(lines, type_name, links)
    _append_issuer_footer(lines, unsubscribe_url=_s(links.get("unsubscribe_url")))
    return "\n".join(lines)


def is_diagnosis_result_email_enabled() -> bool:
    return os.environ.get("DIAG_RESULT_EMAIL_ENABLED", "").strip() == "1"


def _smtp_port() -> int:
    raw = os.environ.get("SMTP_PORT", "587").strip()
    try:
        return int(raw)
    except ValueError:
        return 587


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    return raw.strip() == "1"


def _mail_body_legacy(payload: Dict[str, Any]) -> str:
    base = (
        "魂のナビ診断の結果サマリをお届けします。\n\n"
        f"■ タイプ\n{payload.get('type_name', '（不明）')}\n\n"
        f"■ いまの受信状態\n{payload.get('alignment_state', '（不明）')}\n\n"
        f"■ 意識レベル / エネルギー\n"
        f"{payload.get('consciousness_level', '（不明）')} "
        f"（{payload.get('consciousness_label', '')} / {payload.get('consciousness_emotion', '')}） / "
        f"{payload.get('energy_score', '（不明）')}点\n\n"
        f"■ 身体感覚の目安\n{payload.get('body_signal_summary', '')}\n\n"
        f"■ いまのズレ\n{payload.get('misalignment_reason', '')}\n\n"
        f"■ 一致したときの未来\n{payload.get('future_if_aligned', '')}\n\n"
        f"■ 今やるべき一歩\n{payload.get('next_action', '')}\n\n"
        "※この数値は評価ではなく、いまの判断モードの目安です。\n"
        "※状態は日によって上下します。低く出ても固定ではありません。\n"
    )
    video = str(payload.get("guide_video_url") or "").strip()
    extra = ""
    if video:
        title = str(payload.get("guide_video_title") or "").strip() or "LINE登録後に、整え方の動画を受け取る"
        extra += f"\n■ {title}\n{video}\n"
    return base + extra


def _mail_body(payload: Dict[str, Any]) -> str:
    """診断結果メール本文。full_result_plaintext があればそれを優先（結果ページ相当のテキスト）。"""
    if os.environ.get("DIAG_RESULT_EMAIL_LEGACY", "").strip() == "1":
        return _mail_body_legacy(payload)
    full = str(payload.get("full_result_plaintext") or "").strip()
    if full:
        return full
    return _mail_body_legacy(payload)


def send_diagnosis_result_email(
    *,
    to_email: str,
    to_name: str,
    payload: Dict[str, Any],
) -> Tuple[bool, str]:
    if not is_diagnosis_result_email_enabled():
        return False, "DIAG_RESULT_EMAIL_ENABLED is not enabled"

    host = os.environ.get("SMTP_HOST", "").strip()
    from_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not host or not from_email:
        return False, "SMTP_HOST or SMTP_FROM_EMAIL is missing"

    custom_subj = os.environ.get("DIAG_RESULT_EMAIL_SUBJECT", "").strip()
    type_nm = str(payload.get("type_name") or "").strip()
    if custom_subj:
        subject = custom_subj
    elif type_nm:
        subject = f"【魂のナビ診断】{type_nm}の診断結果（テキスト）"
    else:
        subject = "【魂のナビ診断】診断結果"
    from_name = os.environ.get("SMTP_FROM_NAME", "").strip() or "魂のナビ診断"
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()
    reply_to = os.environ.get("SMTP_REPLY_TO", "").strip()
    bcc = os.environ.get("DIAG_RESULT_EMAIL_BCC", "").strip()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email.strip()
    if reply_to:
        msg["Reply-To"] = reply_to
    if bcc:
        msg["Bcc"] = bcc
    body = _strip_diagnosis_email_promo_footer(_mail_body(payload))
    tn = to_name.strip()
    if tn and not body.lstrip().startswith(f"{tn} 様"):
        body = f"{tn} 様\n\n{body}"
    msg.set_content(body)

    use_ssl = _bool_env("SMTP_USE_SSL", False)
    use_starttls = _bool_env("SMTP_USE_STARTTLS", True)
    timeout_sec = float(os.environ.get("SMTP_TIMEOUT_SEC", "15").strip() or "15")
    port = _smtp_port()

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout_sec) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout_sec) as server:
                server.ehlo()
                if use_starttls:
                    server.starttls()
                    server.ehlo()
                if smtp_user:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return True, "sent"
    except Exception as e:  # pragma: no cover
        name = to_name.strip() if to_name else ""
        suffix = f" ({name})" if name else ""
        return False, f"send failed for {to_email}{suffix}: {type(e).__name__}: {e}"
