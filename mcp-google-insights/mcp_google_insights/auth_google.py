"""
Google API 用サービスアカウント認証。

Allowlist 用メモ:
  - スコープは次の2つのみ（いずれも *readonly*）。サイトの設定変更・データ書き込みは不可。
  - webmasters.readonly … Search Console 検索アナリティクスの読取
  - analytics.readonly … GA4 Data API の読取
"""

from __future__ import annotations

from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build

from mcp_google_insights.config import service_account_json_path

SCOPES = (
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
)


@lru_cache(maxsize=1)
def credentials():
    return service_account.Credentials.from_service_account_file(
        service_account_json_path(),
        scopes=SCOPES,
    )


@lru_cache(maxsize=1)
def search_console_service():
    return build("searchconsole", "v1", credentials=credentials(), cache_discovery=False)


@lru_cache(maxsize=1)
def analytics_data_service():
    return build("analyticsdata", "v1beta", credentials=credentials(), cache_discovery=False)
