"""Mattermost REST API client (v4)."""
from __future__ import annotations

from typing import Any

import httpx


class MattermostError(Exception):
    """Base class for Mattermost API errors."""


class AuthError(MattermostError):
    """401 / 403 — token missing, invalid, or expired."""


class MattermostClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=f"{self.base_url}/api/v4",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MattermostClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self._client.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise MattermostError(f"network error: {e}") from e
        if r.status_code in (401, 403):
            raise AuthError(f"unauthorized ({r.status_code}) — token may be expired")
        if r.status_code >= 400:
            raise MattermostError(f"API error {r.status_code}: {r.text[:200]}")
        if not r.content:
            return None
        return r.json()

    # --- Endpoints used in P1 ---

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/users/me")

    def my_teams(self) -> list[dict[str, Any]]:
        return self._request("GET", "/users/me/teams")

    def my_channels(self, team_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/users/me/teams/{team_id}/channels")

    # --- Endpoints used in P2 ---

    def channel_posts(
        self,
        channel_id: str,
        *,
        page: int = 0,
        per_page: int = 200,
        since: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if since is not None:
            params["since"] = since
        return self._request("GET", f"/channels/{channel_id}/posts", params=params)

    def user(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/users/{user_id}")
