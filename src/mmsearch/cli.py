"""CLI のエントリポイント。typer ベースで全コマンドを定義する。"""
from __future__ import annotations

import re
import webbrowser
from datetime import UTC, datetime

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

from . import __version__, auth, client, config, db, tokens
from . import search as search_engine
from . import sync as sync_engine

NOT_CONFIGURED_HINT = (
    "Run [bold]mmsearch init[/bold] to set up, "
    "or [bold]mmsearch login[/bold] if config exists but token is missing."
)
TOKEN_MISSING_HINT = (
    "Run [bold]mmsearch login[/bold] (browser auto-detect) "
    "or [bold]mmsearch token-refresh[/bold] (manual paste)."
)

app = typer.Typer(
    name="mmsearch",
    help="Mattermost のメッセージをローカルで全文検索する CLI ツール",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)


@app.command()
def version() -> None:
    """バージョンを表示する。"""
    console.print(f"mmsearch {__version__}")


@app.command()
def doctor() -> None:
    """設定とサーバ接続を確認する。"""
    cfg = config.Config.load()
    console.print(f"config:  {config.config_path()}")
    console.print(f"db:      {config.db_path()}")
    console.print(f"storage: {tokens.storage_location()}")

    if not cfg.server_url:
        err.print(f"[red]✗[/red] server_url not configured. {NOT_CONFIGURED_HINT}")
        raise typer.Exit(1)
    console.print(f"server:  {cfg.server_url}")

    token = tokens.load_token()
    if not token:
        err.print(f"[red]✗[/red] no token saved. {TOKEN_MISSING_HINT}")
        raise typer.Exit(1)

    try:
        with client.MattermostClient(cfg.server_url, token) as c:
            me = c.me()
            console.print(f"[green]✓[/green] authenticated as @{me['username']}")
    except client.AuthError as e:
        err.print(f"[red]✗[/red] {e}")
        err.print(TOKEN_MISSING_HINT)
        raise typer.Exit(1) from e
    except client.MattermostError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e


def _validate_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url:
        raise ValueError("URL is required")
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    return url


def _acquire_token(server_url: str, *, prefer_browser: bool, browser: str) -> str:
    """トークンを取得する。ブラウザCookie抽出または手動ペーストで実現。"""
    if prefer_browser:
        console.print(f"\n[dim]Extracting MMAUTHTOKEN from browser ({browser})...[/dim]")
        try:
            token, used = auth.extract_cookie(server_url, browser=browser)
        except auth.CookieError as e:
            err.print(f"[red]✗[/red] {e}")
            raise typer.Exit(1) from e
        console.print(f"[green]✓[/green] cookie extracted from [bold]{used}[/bold]")
        return token

    token = typer.prompt(
        "MMAUTHTOKEN (browser DevTools → Cookies)", hide_input=True
    ).strip()
    if not token:
        err.print("[red]✗[/red] token is required")
        raise typer.Exit(1)
    return token


def _verify_and_get_teams(server_url: str, token: str) -> list[dict]:
    """`/users/me` を叩いてトークンを検証し、続けて所属チーム一覧を返す。"""
    try:
        with client.MattermostClient(server_url, token) as c:
            me = c.me()
            console.print(f"[green]✓[/green] authenticated as @{me['username']}")
            return c.my_teams()
    except client.MattermostError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e


@app.command()
def init(
    browser: str = typer.Option(
        "auto", "--browser", help="Cookie 自動抽出に使うブラウザ"
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="ブラウザ抽出をスキップして手動ペーストする"
    ),
) -> None:
    """対話形式でセットアップウィザードを実行する。"""
    console.print("[bold]mmsearch initial setup[/bold]\n")

    while True:
        raw = typer.prompt("Mattermost URL (例: https://mattermost.example.com)")
        try:
            server_url = _validate_url(raw)
            break
        except ValueError as e:
            err.print(f"[red]✗[/red] {e}")

    if no_browser:
        prefer_browser = False
    else:
        prefer_browser = typer.confirm(
            "Extract MMAUTHTOKEN automatically from your browser?", default=True
        )

    token = _acquire_token(server_url, prefer_browser=prefer_browser, browser=browser)

    console.print("\n[dim]Verifying connection...[/dim]")
    teams = _verify_and_get_teams(server_url, token)

    if not teams:
        err.print("[red]✗[/red] no teams found for this account")
        raise typer.Exit(1)

    if len(teams) == 1:
        team = teams[0]
        console.print(f"team: {team['display_name']} (auto-selected)")
    else:
        console.print("\nteams:")
        for i, t in enumerate(teams):
            console.print(f"  [{i}] {t['display_name']} ({t['name']})")
        idx = int(typer.prompt("Select team index", default="0"))
        team = teams[idx]

    cfg = config.Config(server_url=server_url, team_id=team["id"])
    cfg.save()
    where = tokens.save_token(token)
    db.init_db()

    console.print(f"\n[green]✓[/green] config saved → {config.config_path()}")
    console.print(f"[green]✓[/green] token saved via [bold]{where}[/bold]")
    console.print(f"[green]✓[/green] db initialized → {config.db_path()}")
    console.print("\nNext: [bold]mmsearch sync[/bold]")


@app.command()
def login(
    browser: str = typer.Option(
        "auto",
        "--browser",
        help="ブラウザ: auto/chrome/chromium/firefox/edge/brave/vivaldi/opera/safari",
    ),
) -> None:
    """ブラウザの Cookie から `MMAUTHTOKEN` を再取得して保存する。"""
    cfg = config.Config.load()
    if not cfg.server_url:
        err.print(f"[red]✗[/red] not configured. {NOT_CONFIGURED_HINT}")
        raise typer.Exit(1)

    token = _acquire_token(cfg.server_url, prefer_browser=True, browser=browser)

    console.print("[dim]Verifying token...[/dim]")
    try:
        with client.MattermostClient(cfg.server_url, token) as c:
            me = c.me()
            console.print(f"[green]✓[/green] authenticated as @{me['username']}")
    except client.MattermostError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e

    where = tokens.save_token(token)
    console.print(f"[green]✓[/green] token saved via [bold]{where}[/bold]")


@app.command()
def reset(
    config_only: bool = typer.Option(
        False, "--config", help="設定とトークンのみ削除（DBは残す）"
    ),
    db_only: bool = typer.Option(
        False, "--db", help="DBのみ削除（設定とトークンは残す）"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="確認プロンプトをスキップする"
    ),
) -> None:
    """ローカルデータを削除する: 設定 / 保存済みトークン / DB。"""
    if config_only and db_only:
        err.print("[red]✗[/red] cannot specify both --config and --db")
        raise typer.Exit(2)

    do_config = not db_only
    do_db = not config_only

    targets: list[str] = []
    if do_config:
        targets.append(f"config:   {config.config_path()}")
        targets.append("token:    keyring entry + fallback file")
    if do_db:
        targets.append(f"database: {config.db_path()}")

    console.print("[bold]Will delete:[/bold]")
    for t in targets:
        console.print(f"  - {t}")

    if not yes and not typer.confirm("\nProceed?", default=False):
        console.print("aborted.")
        return

    if do_config:
        cp = config.config_path()
        if cp.exists():
            cp.unlink()
            console.print(f"[green]✓[/green] removed {cp}")
        tokens.delete_token()
        console.print("[green]✓[/green] removed token")

    if do_db:
        dp = config.db_path()
        for p in (dp, dp.parent / (dp.name + "-wal"), dp.parent / (dp.name + "-shm")):
            if p.exists():
                p.unlink()
                console.print(f"[green]✓[/green] removed {p}")


@app.command(name="token-refresh")
def token_refresh() -> None:
    """手動ペーストでトークンを更新する（ブラウザ自動取得なら [bold]login[/bold] を推奨）。"""
    cfg = config.Config.load()
    if not cfg.server_url:
        err.print(f"[red]✗[/red] not configured. {NOT_CONFIGURED_HINT}")
        raise typer.Exit(1)
    token = typer.prompt("New MMAUTHTOKEN", hide_input=True).strip()
    if not token:
        err.print("[red]✗[/red] token is required")
        raise typer.Exit(1)
    try:
        with client.MattermostClient(cfg.server_url, token) as c:
            me = c.me()
            console.print(f"[green]✓[/green] verified as @{me['username']}")
    except client.MattermostError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e
    where = tokens.save_token(token)
    console.print(f"[green]✓[/green] token updated (via {where})")


@app.command()
def sync(
    full: bool = typer.Option(
        False, "--full", help="差分同期ではなく最初からフル同期する"
    ),
) -> None:
    """Mattermost の投稿をローカルDBに同期する。"""
    cfg = config.Config.load()
    if not cfg.server_url or not cfg.team_id:
        err.print(f"[red]✗[/red] not configured. {NOT_CONFIGURED_HINT}")
        raise typer.Exit(1)

    token = tokens.load_token()
    if not token:
        err.print(f"[red]✗[/red] no token saved. {TOKEN_MISSING_HINT}")
        raise typer.Exit(1)

    db.init_db()
    user_cache: set[str] = set()
    grand_total = 0

    try:
        with client.MattermostClient(cfg.server_url, token) as c:
            try:
                channels = sync_engine.fetch_channels(c, cfg)
            except client.AuthError as e:
                err.print(f"[red]✗[/red] {e}")
                err.print(TOKEN_MISSING_HINT)
                raise typer.Exit(1) from e

            if not channels:
                console.print("[yellow]no channels to sync[/yellow]")
                return

            mode = "[bold]full[/bold]" if full else "incremental"
            console.print(f"syncing {len(channels)} channel(s) ({mode})...")

            with Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(bar_width=20),
                TextColumn("{task.completed} posts"),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            ) as progress:
                for ch in channels:
                    name = ch.get("display_name") or ch["name"] or ch["id"][:8]
                    tid = progress.add_task(f"#{name}", total=None)

                    def _bump(n: int, tid: int = tid) -> None:
                        progress.update(tid, advance=n)

                    with db.transaction() as conn:
                        sync_engine.upsert_channel(conn, ch)
                        n = sync_engine.sync_channel(
                            conn,
                            c,
                            ch,
                            full=full,
                            user_cache=user_cache,
                            on_progress=_bump,
                        )
                    progress.update(tid, total=max(n, 1), completed=n)
                    grand_total += n
    except client.MattermostError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e

    console.print(f"\n[green]✓[/green] {grand_total} post(s) synced")


def _format_timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )


def _make_snippet(message: str, query: str, max_len: int = 280) -> tuple[str, bool, bool]:
    """投稿本文からマッチ箇所周辺を切り出す。

    戻り値: (スニペット, 前方省略あり, 後方省略あり)。マッチ位置を中心に
    前後の文脈を残しつつ全体を `max_len` 文字以内に収める。
    """
    if len(message) <= max_len:
        return message, False, False
    idx = message.lower().find(query.lower())
    if idx == -1:
        return message[:max_len], False, True
    start = max(0, idx - max_len // 3)
    end = min(len(message), start + max_len)
    return message[start:end], start > 0, end < len(message)


def _render_hit(hit, query: str) -> None:
    snippet, has_pre, has_post = _make_snippet(hit.message, query)
    snippet = snippet.replace("\n", " ⏎ ")
    if has_pre:
        snippet = "…" + snippet
    if has_post:
        snippet = snippet + "…"

    text = Text(snippet)
    text.highlight_regex(re.escape(query), style="bold black on yellow")

    header = Text()
    header.append(f"#{hit.channel_display_name}", style="cyan bold")
    header.append("  ")
    header.append(_format_timestamp(hit.create_at), style="dim")
    header.append("  ")
    header.append(f"@{hit.username}", style="green")

    console.print(header)
    console.print("  ", text)
    console.print(f"  [dim]→ {hit.post_id}[/dim]")
    console.print()


@app.command()
def search(
    query: str = typer.Argument(..., help="検索キーワード（部分一致）"),
    channel: str = typer.Option(
        None, "--channel", "-c", help="チャンネル名で絞り込む（部分一致）"
    ),
    user: str = typer.Option(
        None, "--user", "-u", help="ユーザー名で絞り込む（完全一致）"
    ),
    since: str = typer.Option(
        None, "--since", help="この日付以降（YYYY-MM-DD または YYYY-MM-DDTHH:MM）"
    ),
    until: str = typer.Option(
        None, "--until", help="この日付以前（YYYY-MM-DD または YYYY-MM-DDTHH:MM）"
    ),
    limit: int = typer.Option(
        search_engine.DEFAULT_LIMIT, "--limit", "-n", help="最大件数"
    ),
    all_results: bool = typer.Option(
        False, "--all", help="件数制限を無視して全件取得する"
    ),
) -> None:
    """ローカルDBから投稿を検索する。"""
    db.init_db()
    effective_limit = None if all_results else limit
    try:
        hits = search_engine.search(
            query,
            channel=channel,
            user=user,
            since=since,
            until=until,
            limit=effective_limit,
        )
    except ValueError as e:
        err.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1) from e

    if not hits:
        console.print("[yellow]no results[/yellow]")
        return

    for h in hits:
        _render_hit(h, query)

    count = len(hits)
    if effective_limit is not None and count >= effective_limit:
        console.print(
            f"[dim]{count} result(s) shown[/dim] "
            f"[yellow]— limit reached, more may exist. Use [bold]-n {count * 2}[/bold] "
            f"or [bold]--all[/bold] to see more.[/yellow]"
        )
    else:
        console.print(f"[dim]{count} result(s)[/dim]")


@app.command(name="open")
def open_(
    post_id: str = typer.Argument(..., help="投稿ID（検索結果の各ヒット末尾に表示される）"),
    print_only: bool = typer.Option(
        False, "--print", help="ブラウザを開かずURLだけ表示する"
    ),
) -> None:
    """既定のブラウザで投稿を開く。"""
    cfg = config.Config.load()
    if not cfg.server_url:
        err.print(f"[red]✗[/red] not configured. {NOT_CONFIGURED_HINT}")
        raise typer.Exit(1)

    db.init_db()
    url = search_engine.make_permalink(cfg.server_url, post_id)
    post = search_engine.get_post(post_id)
    if post:
        console.print(f"#{post['channel_name']}  @{post['username']}")
        console.print(f"[dim]{_format_timestamp(post['create_at'])}[/dim]")

    if print_only:
        console.print(url)
        return

    if webbrowser.open(url):
        console.print(f"[green]✓[/green] opened: {url}")
    else:
        console.print(f"[yellow]could not auto-open. URL:[/yellow] {url}")


@app.command()
def channels() -> None:
    """同期済みチャンネルの一覧と最終同期日時を表示する。"""
    db.init_db()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, c.display_name, c.type, c.last_synced_at, "
            "       (SELECT COUNT(*) FROM posts p WHERE p.channel_id = c.id) AS posts "
            "FROM channels c ORDER BY posts DESC, c.display_name"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        console.print("[yellow]no channels synced yet. Run [bold]mmsearch sync[/bold].[/yellow]")
        return

    for r in rows:
        last = "never" if not r["last_synced_at"] else _format_timestamp(r["last_synced_at"])
        console.print(
            f"[cyan]#{r['display_name']}[/cyan] "
            f"[dim]({r['name']}, {r['type']})[/dim]  "
            f"{r['posts']} posts  "
            f"[dim]last: {last}[/dim]"
        )


if __name__ == "__main__":
    app()
