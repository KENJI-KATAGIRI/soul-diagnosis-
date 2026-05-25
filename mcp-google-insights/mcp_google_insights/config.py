"""環境変数からサイト別の GSC / GA4 設定を読み込む。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

# パッケージの親（mcp-google-insights/）直下の .env を試す
_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _ROOT.parent
load_dotenv(_ROOT / ".env")
load_dotenv()  # CWD の .env
# リポジトリ直下の .env（Flask 用など）を後から読み、同名キーはこちらを優先
load_dotenv(_REPO_ROOT / ".env", override=True)


@dataclass(frozen=True)
class SiteProfile:
    """1 サイト分の Search Console サイト URL と GA4 プロパティ ID。"""

    key: str
    gsc_site_url: str
    ga4_property_id: str  # 数値のみ（API では properties/{id}）


def _strip_optional_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
        return v[1:-1]
    return v


def _optional_env(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return _strip_optional_quotes(str(raw))


def service_account_json_path() -> str:
    """サービスアカウント JSON の絶対パス。"""
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get(
        "GCP_SERVICE_ACCOUNT_JSON_PATH"
    )
    if not path or not str(path).strip():
        raise ValueError(
            "GOOGLE_APPLICATION_CREDENTIALS（または GCP_SERVICE_ACCOUNT_JSON_PATH）に "
            "サービスアカウント JSON の絶対パスを設定してください。"
        )
    p = Path(_strip_optional_quotes(str(path))).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"認証ファイルが見つかりません: {p}")
    return str(p.resolve())


def load_sites() -> Dict[str, SiteProfile]:
    """
    利用可能なサイトキーとプロファイル。

    キー: life-energy-coaching | gaiaarts | gaiaarts-hair | tamashiinavi | sprouture | spagency
    """
    sites = {
        "life-energy-coaching": SiteProfile(
            key="life-energy-coaching",
            gsc_site_url=_optional_env(
                "GSC_SITE_LIFE_ENERGY",
                "sc-domain:life-energy-coaching.net",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_LIFE_ENERGY", ""),
        ),
        "gaiaarts": SiteProfile(
            key="gaiaarts",
            gsc_site_url=_optional_env(
                "GSC_SITE_GAIAARTS",
                "sc-domain:gaiaarts.org",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_GAIAARTS", ""),
        ),
        "gaiaarts-hair": SiteProfile(
            key="gaiaarts-hair",
            gsc_site_url=_optional_env(
                "GSC_SITE_GAIAARTS_HAIR",
                "https://gaiaarts.org/hair/",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_GAIAARTS_HAIR", ""),
        ),
        "tamashiinavi": SiteProfile(
            key="tamashiinavi",
            gsc_site_url=_optional_env(
                "GSC_SITE_TAMASHII",
                "https://tamashiinavi.com/navi",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_TAMASHII", ""),
        ),
        "sprouture": SiteProfile(
            key="sprouture",
            gsc_site_url=_optional_env(
                "GSC_SITE_SPROUTURE",
                "https://sprouture.net/",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_SPROUTURE", ""),
        ),
        "spagency": SiteProfile(
            key="spagency",
            gsc_site_url=_optional_env(
                "GSC_SITE_SPAGENCY",
                "https://sp-agency.net/",
            ),
            ga4_property_id=_optional_env("GA4_PROPERTY_ID_SPAGENCY", ""),
        ),
    }
    return sites


def resolve_site(site_key: str) -> SiteProfile:
    """site_key を正規化しプロファイルを返す（GA4 未設定でも返す。GA4 ツール側で別途検証）。"""
    key = (site_key or "").strip().lower().replace("_", "-")
    aliases = {
        "life": "life-energy-coaching",
        "lec": "life-energy-coaching",
        "lifeenergycoaching": "life-energy-coaching",
        "gaia": "gaiaarts",
        "hair": "gaiaarts-hair",
        "gaiaartshair": "gaiaarts-hair",
        "tamashii": "tamashiinavi",
        "navi": "tamashiinavi",
        "sp": "sprouture",
        "spa": "spagency",
        "sp-agency": "spagency",
    }
    key = aliases.get(key, key)
    sites = load_sites()
    if key not in sites:
        allowed = ", ".join(sorted(sites.keys()))
        raise ValueError(f"不明な site_key: {site_key!r}。次のいずれか: {allowed}")
    return sites[key]


def require_ga4_property(prof: SiteProfile) -> str:
    """GA4 プロパティ ID（数値文字列）。未設定なら分かりやすく例外。"""
    pid = (prof.ga4_property_id or "").strip()
    if not pid:
        raise ValueError(
            f"サイト {prof.key} 用の GA4_PROPERTY_ID_* が .env に未設定です。"
            "（Admin → プロパティ設定 → プロパティ ID）"
        )
    return pid
