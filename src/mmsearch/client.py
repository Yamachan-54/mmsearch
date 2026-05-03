"""Mattermost REST API v4 クライアント。"""
from __future__ import annotations

from typing import Any

import httpx


class MattermostError(Exception):
    """Mattermost API 関連エラーの基底クラス。"""


class AuthError(MattermostError):
    """401 / 403 — トークン不在・無効・期限切れを示す。

    呼び出し側で個別にハンドリングしてユーザーに `mmsearch login` 等の
    復旧手順を案内するために、汎用エラーから分離している。
    """


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
            # レスポンス本文には機密情報が含まれる可能性があるため、先頭200文字に制限
            raise MattermostError(f"API error {r.status_code}: {r.text[:200]}")
        if not r.content:
            return None
        return r.json()

    # --- P1 で利用するエンドポイント ---

    def me(self) -> dict[str, Any]:
        """認証情報の検証用。`/users/me` で自分の情報を取得する。"""
        return self._request("GET", "/users/me")

    def my_teams(self) -> list[dict[str, Any]]:
        """自分が所属するチームの一覧を取得する。"""
        return self._request("GET", "/users/me/teams")

    def my_channels(self, team_id: str) -> list[dict[str, Any]]:
        """指定チーム内で自分が参加しているチャンネルの一覧を取得する。"""
        return self._request("GET", f"/users/me/teams/{team_id}/channels")

    # --- P2 で利用するエンドポイント ---

    def channel_posts(
        self,
        channel_id: str,
        *,
        page: int = 0,
        per_page: int = 200,
        since: int | None = None,
    ) -> dict[str, Any]:
        """チャンネルの投稿を取得する。

        - `since` 指定時: それ以降に作成・更新された投稿のみを返す（差分同期用）
        - 未指定時: ページネーションで降順に投稿を返す（フル同期用）
        """
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if since is not None:
            params["since"] = since
        return self._request("GET", f"/channels/{channel_id}/posts", params=params)

    def user(self, user_id: str) -> dict[str, Any]:
        """ユーザー情報を取得する（投稿者名の解決に使用）。"""
        return self._request("GET", f"/users/{user_id}")
