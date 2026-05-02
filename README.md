# mmsearch

Mattermost のメッセージをローカルにインデックス化し、本家より使いやすい全文検索を提供する CLI ツール。

> ⚠️ **重要 / 免責事項**
>
> このツールは **各自の責任** で利用してください。所属するMattermostサーバの利用規約に違反しないか、必ずご自身で確認してください。配布元・コントリビュータは一切の責任を負いません。
>
> 本ツールは取得したメッセージを **完全にローカル** （あなたのマシン内のSQLite）に保存します。サーバ側設定の変更や管理者権限は不要です。

## 特徴

- **2文字の日本語クエリでもヒット** — SQLite FTS5 + trigram tokenizer で短いキーワードでも部分一致
- **完全ローカル** — メッセージはあなたのマシンにのみ保存（追加サーバ・追加バイナリ不要）
- **複合フィルタ** — チャンネル / ユーザー / 日付範囲で絞り込み
- **差分同期** — 2回目以降は新着のみ取得して高速
- **ブラウザで開ける** — 検索結果から該当投稿を一発で開く
- **管理者権限不要** — 自分のアカウントで通常通りログインできれば動く

## 動作要件

- Linux / macOS / WSL2
- Python 3.11+
- Mattermost への通常のログインアクセス
- ターミナルでコマンドを実行できること

## クイックスタート

### 1. インストール

```bash
git clone https://github.com/<your-account>/mmsearch.git
cd mmsearch
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 初期セットアップ

```bash
mmsearch init
```

ウィザードで以下を聞かれます:

- **Mattermost のURL** — 例: `https://mattermost.example.com`
- **MMAUTHTOKEN** — ブラウザのCookieから取得（[詳細手順](docs/SETUP.md)）

### 3. 投稿の同期

```bash
mmsearch sync
```

初回はチャンネル数・投稿量に応じて時間がかかります。2回目以降は差分のみ取得します。

### 4. 検索

```bash
mmsearch search "実装"
mmsearch search "質問" -c "課題" --since 2026-04-01
```

## コマンド一覧

| コマンド | 用途 |
|---------|------|
| `mmsearch init` | 対話式セットアップ |
| `mmsearch doctor` | 設定・接続確認 |
| `mmsearch sync` | 投稿を同期（差分） |
| `mmsearch sync --full` | フル再取得 |
| `mmsearch search "kw"` | 検索（デフォルト最新100件） |
| `mmsearch search "kw" -n 500` | 件数を増やす |
| `mmsearch search "kw" --all` | 全件表示（件数制限なし） |
| `mmsearch search "kw" -c general -u alice --since 2026-04-01` | 複合フィルタ |
| `mmsearch open <post_id>` | ブラウザで該当投稿を開く |
| `mmsearch open <post_id> --print` | URLだけ表示 |
| `mmsearch channels` | 同期済みチャンネル一覧 |
| `mmsearch token-refresh` | トークン更新（セッション切れ時） |
| `mmsearch reset` | ローカルデータ削除 |

`--help` / `-h` で各コマンドの詳細が見られます。

## データの保存場所

| 種類 | パス |
|------|------|
| 設定 | `~/.config/mmsearch/config.toml` |
| トークン | OS keyring / `~/.config/mmsearch/token`（fallback） |
| データベース | `~/.local/share/mmsearch/mmsearch.db` |

`XDG_CONFIG_HOME` / `XDG_DATA_HOME` 環境変数で変更可能。

## ドキュメント

- 📘 [詳細セットアップ手順 (SETUP.md)](docs/SETUP.md) — `MMAUTHTOKEN` の取得方法など
- 🔧 [トラブルシューティング (TROUBLESHOOTING.md)](docs/TROUBLESHOOTING.md) — よくあるエラーと対処

## トークンの取扱い

`MMAUTHTOKEN` は **パスワードと同等の機密情報** です:

- 他人と共有しない
- Gitにコミットしない（`.gitignore` で `token` ファイルは除外済）
- スクリーンショット等で映り込まないよう注意
- ブラウザのMattermostセッションが切れると無効になります（その場合は `mmsearch token-refresh` で再設定）

## 開発

```bash
pip install -e ".[dev]"
pytest          # テスト実行
ruff check .    # lint
```

## ライセンス

[MIT](LICENSE)
