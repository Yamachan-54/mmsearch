"""ブラウザの既存 Cookie から `MMAUTHTOKEN` を抽出する認証モジュール。

ユーザーがすでにブラウザでログイン済みの状態を流用するため、Mattermost 側の
認証方式（ID/Password・SSO・SAML 等）を問わず動作するのが利点。`mmsearch login`
コマンドのバックエンドとして使われる。
"""
from __future__ import annotations

from urllib.parse import urlparse

try:
    import browser_cookie3 as _bc3
except ImportError:
    # browser_cookie3 が未インストールの場合は extract_cookie 内で
    # 親切なエラーメッセージを出すため、ここでは握りつぶす
    _bc3 = None

COOKIE_NAME = "MMAUTHTOKEN"

# 自動検出の試行順。Chromium 系ブラウザはそれぞれ独立したプロファイルディレクトリを
# 持つため `chrome` ひとつで代用できず、個別に列挙する必要がある。
# 順序の方針: 利用率の高いブラウザを先頭に、Chromium 系をまとめて、最後に Safari。
SUPPORTED_BROWSERS = (
    "chrome",
    "chromium",
    "firefox",
    "edge",
    "brave",
    "vivaldi",
    "opera",
    "safari",
)


class CookieError(Exception):
    """Cookie 抽出に失敗した際に投げる例外。"""


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise CookieError(f"invalid URL: {url!r}")
    return parsed.netloc


def _bc3_module():
    """browser_cookie3 モジュールを返す。未インストールなら CookieError。

    関数経由にしているのは、テストでモジュール属性 `_bc3` を monkeypatch で
    差し替え可能にするため。
    """
    if _bc3 is None:
        raise CookieError(
            "browser_cookie3 is not installed. "
            "Run: pip install 'browser-cookie3>=0.19'"
        )
    return _bc3


def _extract_one(browser: str, domain: str):
    """指定された1つのブラウザから Cookie を取り出す。失敗したら例外を投げる。"""
    bc3 = _bc3_module()
    fn = getattr(bc3, browser, None)
    if fn is None:
        raise CookieError(f"unknown browser backend: {browser}")
    jar = fn(domain_name=domain)
    for c in jar:
        if c.name == COOKIE_NAME:
            return c.value
    raise CookieError(f"no {COOKIE_NAME} cookie for {domain}")


def extract_cookie(server_url: str, browser: str = "auto") -> tuple[str, str]:
    """`MMAUTHTOKEN` を抽出して (token, 使用したブラウザ名) を返す。

    `browser='auto'` の場合は `SUPPORTED_BROWSERS` の順で試行し、最初に成功した
    ブラウザの値を返す。特定のブラウザを指定した場合は失敗時に即座に CookieError
    を上げ、呼び出し元が原因を判別できるようにする。
    """
    domain = _domain_from_url(server_url)

    if browser == "auto":
        candidates = SUPPORTED_BROWSERS
    elif browser in SUPPORTED_BROWSERS:
        candidates = (browser,)
    else:
        raise CookieError(
            f"unknown browser {browser!r}. "
            f"Choose from: auto, {', '.join(SUPPORTED_BROWSERS)}"
        )

    errors: list[str] = []
    for name in candidates:
        try:
            token = _extract_one(name, domain)
        except Exception as e:
            errors.append(f"  - {name}: {e}")
            continue
        return token, name

    raise CookieError(
        f"could not extract {COOKIE_NAME} for {domain} from any browser:\n"
        + "\n".join(errors)
        + "\n\nMake sure you are logged into Mattermost in a supported browser, "
        "then try again. If the issue persists, fall back to manual paste: "
        "`mmsearch token-refresh`."
    )
