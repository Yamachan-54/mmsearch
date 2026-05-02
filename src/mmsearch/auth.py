"""Browser cookie extraction for Mattermost authentication.

Reads the `MMAUTHTOKEN` cookie from the user's existing browser session,
so they never have to manually paste it from DevTools. Works with Chrome,
Firefox, Edge, Brave, and Safari (the latter only on macOS).

This is the `mmsearch login` flow — works regardless of the server's
authentication method (password / SSO / SAML), since we read the cookie
that the browser already obtained after a successful interactive login.
"""
from __future__ import annotations

from urllib.parse import urlparse

try:
    import browser_cookie3 as _bc3
except ImportError:
    _bc3 = None

COOKIE_NAME = "MMAUTHTOKEN"

# Detection order: most-popular first. Brave shares Chrome's profile format
# but is checked separately because its profile lives elsewhere.
SUPPORTED_BROWSERS = ("chrome", "firefox", "edge", "brave", "safari")


class CookieError(Exception):
    """Cookie extraction failed."""


def _domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc:
        raise CookieError(f"invalid URL: {url!r}")
    return parsed.netloc


def _bc3_module():
    """Return the browser_cookie3 module, raising CookieError if unavailable.
    Re-imported each call so test monkeypatching of the alias works.
    """
    if _bc3 is None:
        raise CookieError(
            "browser_cookie3 is not installed. "
            "Run: pip install 'browser-cookie3>=0.19'"
        )
    return _bc3


def _extract_one(browser: str, domain: str):
    """Try one browser; return cookie value or raise."""
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
    """Return (token, browser_used).

    `browser="auto"` tries each backend in `SUPPORTED_BROWSERS` order and
    returns the first hit. Specific browsers raise `CookieError` immediately
    on failure so callers can give precise diagnostics.
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
