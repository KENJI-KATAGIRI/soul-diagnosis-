"""
MCP stdio トランスポート（JSON-RPC 2.0、改行区切り）。
Python 3.9 互換。公式 mcp パッケージ（要 3.10+）は使わない。
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

from mcp_google_insights import __version__
from mcp_google_insights.tools_impl import (
    get_ga4_page_report,
    get_search_console_pages,
    get_search_console_queries,
    get_search_console_summary,
    get_weekly_site_summary,
)

# Cursor の mcp.json キーと一致させる（allowlist: Mcp(<ここ>, tool名)）
MCP_SERVER_PUBLIC_NAME = "gsc-ga4-readonly"

ToolFn = Callable[..., str]

# 旧 tool 名（get_*）は tools/call のみ受け付け（Allowlist 移行用）。tools/list には出さない。
LEGACY_TOOL_NAMES: Dict[str, str] = {
    "get_search_console_summary": "readonly_gsc_summary_weeks",
    "get_search_console_pages": "readonly_gsc_top_pages",
    "get_search_console_queries": "readonly_gsc_top_queries",
    "get_ga4_page_report": "readonly_ga4_pages_channels",
    "get_weekly_site_summary": "readonly_weekly_insight_bundle",
}

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "readonly_gsc_summary_weeks",
        "description": (
            "[READ ONLY / Google API 読取専用] Search Console 集計（直近7日と前週7日）。"
            "表示回数・クリック・CTR・平均掲載順位を比較する。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_key": {
                    "type": "string",
                    "description": "life-energy-coaching / gaiaarts / gaiaarts-hair / tamashiinavi / sprouture / spagency",
                },
            },
            "required": ["site_key"],
        },
    },
    {
        "name": "readonly_gsc_top_pages",
        "description": (
            "[READ ONLY / Google API 読取専用] Search Console ページ別（直近7日）。"
            "表示回数・クリック・CTR・順位。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_key": {
                    "type": "string",
                    "description": "life-energy-coaching / gaiaarts / gaiaarts-hair / tamashiinavi / sprouture / spagency",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "最大行数（既定100、最大500）",
                    "default": 100,
                },
            },
            "required": ["site_key"],
        },
    },
    {
        "name": "readonly_gsc_top_queries",
        "description": (
            "[READ ONLY / Google API 読取専用] Search Console クエリ別（直近7日）。"
            "表示回数・クリック・CTR・順位。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_key": {
                    "type": "string",
                    "description": "life-energy-coaching / gaiaarts / gaiaarts-hair / tamashiinavi / sprouture / spagency",
                },
                "row_limit": {
                    "type": "integer",
                    "description": "最大行数（既定100、最大500）",
                    "default": 100,
                },
            },
            "required": ["site_key"],
        },
    },
    {
        "name": "readonly_ga4_pages_channels",
        "description": (
            "[READ ONLY / Google API 読取専用] GA4 ページ・チャネル（直近7日と前週7日比較）。"
            "よく見られているページと流入のざっくり傾向。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_key": {
                    "type": "string",
                    "description": "life-energy-coaching / gaiaarts / gaiaarts-hair / tamashiinavi / sprouture / spagency（.env の GA4 ID と対応）",
                },
                "page_row_limit": {
                    "type": "integer",
                    "description": "ページ行の上限（既定40）",
                    "default": 40,
                },
            },
            "required": ["site_key"],
        },
    },
    {
        "name": "readonly_weekly_insight_bundle",
        "description": (
            "[READ ONLY / Google API 読取専用] GSC+GA4 を統合し、改善候補・CTR・コラム題材・内部リンク候補を返す。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "site_key": {
                    "type": "string",
                    "description": "life-energy-coaching / gaiaarts / gaiaarts-hair / tamashiinavi / sprouture / spagency",
                },
            },
            "required": ["site_key"],
        },
    },
]

TOOL_DISPATCH: Dict[str, ToolFn] = {
    "readonly_gsc_summary_weeks": lambda a: get_search_console_summary(
        str(a.get("site_key", ""))
    ),
    "readonly_gsc_top_pages": lambda a: get_search_console_pages(
        str(a.get("site_key", "")),
        int(a.get("row_limit") or 100),
    ),
    "readonly_gsc_top_queries": lambda a: get_search_console_queries(
        str(a.get("site_key", "")),
        int(a.get("row_limit") or 100),
    ),
    "readonly_ga4_pages_channels": lambda a: get_ga4_page_report(
        str(a.get("site_key", "")),
        int(a.get("page_row_limit") or 40),
    ),
    "readonly_weekly_insight_bundle": lambda a: get_weekly_site_summary(
        str(a.get("site_key", ""))
    ),
}


def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(req_id: Optional[Any], code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )


def _result(req_id: Any, result: Any) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _tool_success(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _tool_error(text: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def handle_request(msg: Dict[str, Any]) -> None:
    method = msg.get("method")
    params = msg.get("params") or {}

    if method is None:
        if "id" in msg:
            _error(msg.get("id"), -32600, "Invalid Request")
        return

    # JSON-RPC の notification（id なし）— 応答しない
    if "id" not in msg:
        return

    req_id = msg["id"]

    if method == "initialize":
        client_proto = params.get("protocolVersion") or "2024-11-05"
        _result(
            req_id,
            {
                "protocolVersion": client_proto,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": MCP_SERVER_PUBLIC_NAME,
                    "version": __version__,
                },
            },
        )
        return

    if method == "tools/list":
        _result(req_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        name = (params.get("name") or "").strip()
        canonical = LEGACY_TOOL_NAMES.get(name, name)
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        fn = TOOL_DISPATCH.get(canonical)
        if not fn:
            _result(req_id, _tool_error(f"未知の tool: {name}"))
            return
        try:
            text = fn(arguments)
            _result(req_id, _tool_success(text))
        except Exception as e:
            tb = traceback.format_exc()
            err_text = f"{type(e).__name__}: {e}\n\n{tb}"
            _result(req_id, _tool_error(err_text))
        return

    if method == "ping":
        _result(req_id, {})
        return

    if "id" in msg:
        _error(req_id, -32601, f"Method not found: {method}")


def run_stdio_loop() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            _error(None, -32700, f"Parse error: {e}")
            continue
        if not isinstance(msg, dict):
            _error(None, -32600, "Invalid Request")
            continue
        try:
            if "method" in msg:
                handle_request(msg)
            elif "id" in msg:
                _error(msg.get("id"), -32600, "Invalid Request")
        except BrokenPipeError:
            break
        except Exception as e:
            _error(msg.get("id"), -32603, f"Internal error: {e}")
